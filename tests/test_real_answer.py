import hashlib
import pytest
from rainclass.browser import Browser
from rainclass.real_answer import RealAnswer,AnswerStopped
from rainclass.real_review import ReviewedDraft

@pytest.fixture
def scene(tmp_path):
    browser=Browser(tmp_path/'rainclass-edge-profile',headless=True)
    page=browser.open('about:blank')
    class Page:
        url='https://www.yuketang.cn/lesson/fullscreen/v3/123/exercise/7'
        def locator(self,*a,**k):return page.locator(*a,**k)
        def evaluate(self,*a,**k):return page.evaluate(*a,**k)
        def wait_for_timeout(self,*a):return page.wait_for_timeout(*a)
    wrapper=Page()
    yield page,wrapper,RealAnswer(tmp_path/'attempts.json')
    browser.close()

def setup(page,wrapper,kind='single',receipt=True):
    wrapper.url='https://www.yuketang.cn/lesson/fullscreen/v3/123/'+('blank' if kind=='blank' else 'exercise')+'/7'
    mode='blank' if kind=='blank' else 'exercise'
    key=hashlib.sha256(f'123/{mode}/7'.encode()).hexdigest()
    labels=''.join(f'<button class="options-label" aria-checked="false" onclick="'+("document.querySelectorAll('.options-label').forEach(x=>x.setAttribute('aria-checked','false'));" if kind=='single' else '')+f"this.setAttribute('aria-checked',this.getAttribute('aria-checked')==='true'?'false':'true')\">{a}</button>" for a in 'ABC')
    controls='<input><input>' if kind=='blank' else labels
    page.set_content('<script>window.submits=0</script><div class="slide__cmp"><section class="slide__wrap"><img class="cover"><div class="time-box"><div class="timing">01:20</div></div>'+controls+'<button class="submit-btn" onclick="window.submits++;'+("this.innerText='已提交'" if receipt else '')+'">提交答案</button></section></div>')
    draft=ReviewedDraft(key,'rev',kind,'题干',() if kind=='blank' else ('one','two','three'),2 if kind=='blank' else 0)
    result=dict(suggested_answer=['x','y'] if kind=='blank' else ['A','C'] if kind=='multiple' else ['B'],explanation='参考',uncertainty='待核实')
    return draft,result

@pytest.mark.parametrize('kind',['single','multiple','blank'])
def test_real_fill_submit_receipt_and_durable_dedup(scene,kind):
    p,w,a=scene;d,r=setup(p,w,kind)
    assert '已填写并提交' in a.execute(w,d,r,lambda:None)
    assert p.evaluate('window.submits')==1
    with pytest.raises(AnswerStopped):RealAnswer(a.path).execute(w,d,r,lambda:None)
    assert p.evaluate('window.submits')==1
    if kind=='blank':assert p.locator('input').evaluate_all('(nodes)=>nodes.map(n=>n.value)')==['x','y']

def test_changed_question_and_cancel_do_not_write(scene):
    p,w,a=scene;d,r=setup(p,w)
    w.url=w.url.replace('/7','/8')
    with pytest.raises(AnswerStopped):a.execute(w,d,r,lambda:None)
    assert p.evaluate('window.submits')==0

def test_mapping_failure_does_not_submit(scene):
    p,w,a=scene;d,r=setup(p,w)
    p.locator('.options-label').last.evaluate('(e)=>e.remove()')
    with pytest.raises(AnswerStopped):a.execute(w,d,r,lambda:None)
    assert p.evaluate('window.submits')==0

def test_unknown_receipt_never_retries(scene):
    p,w,a=scene;d,r=setup(p,w,receipt=False)
    assert '状态未知' in a.execute(w,d,r,lambda:None)
    with pytest.raises(AnswerStopped):a.execute(w,d,r,lambda:None)
    assert p.evaluate('window.submits')==1

def test_cancel_between_fill_and_submit(scene):
    p,w,a=scene;d,r=setup(p,w,'blank');steps=[]
    def guard():
        steps.append(1)
        if p.locator('input').first.input_value():raise AnswerStopped('cancel')
    with pytest.raises(AnswerStopped):a.execute(w,d,r,guard)
    assert p.evaluate('window.submits')==0

def test_obscured_option_reports_stage_without_submission(scene):
    p,w,a=scene;d,r=setup(p,w)
    p.evaluate("""() => {const b=document.createElement('div');b.style='position:fixed;inset:0;z-index:10000;background:transparent';document.body.appendChild(b)}""")
    with pytest.raises(AnswerStopped,match='选择选项 B.*遮挡'):a.execute(w,d,r,lambda:None)
    assert p.evaluate('window.submits')==0 and not a.path.exists()


def test_timeout_reports_presubmit_stage(scene,monkeypatch):
    from playwright.sync_api import TimeoutError
    p,w,a=scene;d,r=setup(p,w);trace=[];a.trace=lambda **kw:trace.append(kw)
    def fail(*args):raise TimeoutError('element is not stable')
    monkeypatch.setattr(a,'click',fail)
    with pytest.raises(AnswerStopped,match='选择选项 B失败.*ANIMATING.*尚未点击提交'):a.execute(w,d,r,lambda:None)
    assert trace[-1]['submit_attempted'] is False
    assert p.evaluate('window.submits')==0

def drawer_setup(p,w,opened=False,count=2,reverse=False):
    d,r=setup(p,w,'blank')
    p.locator('.slide__wrap input').evaluate_all('(nodes)=>nodes.forEach(n=>n.remove())')
    p.locator('.submit-btn').evaluate("e=>{e.innerText='作答';e.onclick=()=>{window.opens=(window.opens||0)+1;setTimeout(()=>document.querySelector('#drawer').style.display='block',100)}}")
    indices=list(range(1,count+1))
    if reverse:indices.reverse()
    rows=''.join(f'<div><span>{i}</span><input placeholder="输入答案"></div>' for i in indices)
    p.evaluate("html=>document.body.insertAdjacentHTML('beforeend',html)",f'''<input id="unrelated" value="keep"><aside id="drawer" style="display:{'block' if opened else 'none'}"><header><span>填空题作答</span></header><main>{rows}</main><footer><button onclick="window.submits++;this.innerText='已提交'">提交答案</button></footer></aside>''')
    return d,r

@pytest.mark.parametrize('opened',[False,True])
def test_blank_separate_drawer_opens_fills_and_submits(scene,opened):
    p,w,a=scene;d,r=drawer_setup(p,w,opened=opened)
    assert '已填写并提交' in a.execute(w,d,r,lambda:None)
    assert p.locator('#drawer input').evaluate_all('(nodes)=>nodes.map(n=>n.value)')==['x','y']
    assert p.locator('#unrelated').input_value()=='keep'
    assert p.evaluate('window.submits')==1
    assert p.evaluate('window.opens||0')==(0 if opened else 1)

def test_blank_drawer_orders_numbered_blanks(scene):
    p,w,a=scene;d,r=drawer_setup(p,w,opened=True,reverse=True)
    a.execute(w,d,r,lambda:None)
    assert p.locator('#drawer input').evaluate_all('(nodes)=>nodes.map(n=>n.value)')==['y','x']

def test_blank_drawer_mismatch_never_fills(scene):
    p,w,a=scene;d,r=drawer_setup(p,w,opened=True,count=1)
    with pytest.raises(AnswerStopped,match='已核对 2 空.*编辑器 1 个'):a.execute(w,d,r,lambda:None)
    assert p.locator('#drawer input').input_value()=='' and p.evaluate('window.submits')==0

def test_change_during_drawer_open_never_fills(scene):
    p,w,a=scene;d,r=drawer_setup(p,w)
    def guard():
        if p.evaluate('window.opens||0'):raise AnswerStopped('题目变化')
    with pytest.raises(AnswerStopped):a.execute(w,d,r,guard)
    assert p.evaluate('window.submits')==0

def test_visible_blank_opener_skips_unnecessary_scroll(scene,monkeypatch):
    from playwright.sync_api import ElementHandle
    p,w,a=scene;d,r=drawer_setup(p,w)
    original=ElementHandle.scroll_into_view_if_needed
    def scroll(node,*args,**kwargs):
        if node.inner_text().strip()=='作答':raise AssertionError('visible opener must not scroll')
        return original(node,*args,**kwargs)
    monkeypatch.setattr(ElementHandle,'scroll_into_view_if_needed',scroll)
    assert '已填写并提交' in a.execute(w,d,r,lambda:None)
    assert p.evaluate('window.opens')==1 and p.evaluate('window.submits')==1

@pytest.mark.parametrize('submit',[False,True])
def test_essay_drawer_answer_and_submit_policy(scene,submit):
    from dataclasses import replace
    p,w,a=scene;d,r=drawer_setup(p,w,opened=False,count=1)
    w.url=w.url.replace('/blank/','/subjective/')
    key=hashlib.sha256(b'123/subjective/7').hexdigest()
    d=replace(d,instance_key=key,kind='essay',blank_count=0)
    p.locator('#drawer header span').evaluate("e=>e.innerText='主观题作答'")
    p.locator('#drawer input').evaluate("e=>{const t=document.createElement('textarea');e.replaceWith(t)}")
    r={**r,'suggested_answer':['第一段说明。\n第二段依据。']}
    message=a.execute(w,d,r,lambda:None,submit=submit)
    assert p.locator('#drawer textarea').input_value()==r['suggested_answer'][0]
    assert p.evaluate('window.submits')==int(submit)
    assert ('未点击提交' in message)==(not submit)

def test_essay_smaller_dom_limit_never_truncates_or_submits(scene):
    from dataclasses import replace
    p,w,a=scene;d,r=setup(p,w,'blank')
    w.url=w.url.replace('/blank/','/subjective/')
    d=replace(d,instance_key=hashlib.sha256(b'123/subjective/7').hexdigest(),kind='essay',blank_count=0)
    p.locator('.slide__wrap input').evaluate_all("nodes=>{nodes[0].outerHTML='<textarea maxlength=5></textarea>';nodes[1].remove()}")
    with pytest.raises(AnswerStopped,match='超过页面 5 字限制'):a.execute(w,d,{**r,'suggested_answer':['123456']},lambda:None)
    assert p.locator('textarea').input_value()=='' and p.evaluate('window.submits')==0

def test_essay_upload_control_is_not_an_answer_editor(scene):
    from dataclasses import replace
    p,w,a=scene;d,r=drawer_setup(p,w,opened=True,count=1)
    w.url=w.url.replace('/blank/','/subjective/')
    d=replace(d,instance_key=hashlib.sha256(b'123/subjective/7').hexdigest(),kind='essay',blank_count=0)
    p.locator('#drawer header span').evaluate("e=>e.innerText='主观题作答'")
    p.locator('#drawer main').evaluate("e=>{e.innerHTML='<textarea></textarea><input type=file><input type=color><input type=range><input type=date>'}")
    assert '已填写并提交' in a.execute(w,d,{**r,'suggested_answer':['完整文字答案']},lambda:None)
    assert p.locator('textarea').input_value()=='完整文字答案'
    assert p.locator('input[type=file]').input_value()==''
    assert p.evaluate('window.submits')==1


@pytest.mark.parametrize('kind',['single','blank','essay'])
def test_ready_submit_skips_scroll_timeout(scene,monkeypatch,kind):
    from dataclasses import replace
    from playwright.sync_api import ElementHandle,TimeoutError
    p,w,a=scene
    if kind=='single':d,r=setup(p,w)
    else:
        d,r=drawer_setup(p,w,opened=True,count=1 if kind=='essay' else 2)
        if kind=='essay':
            w.url=w.url.replace('/blank/','/subjective/')
            d=replace(d,instance_key=hashlib.sha256(b'123/subjective/7').hexdigest(),kind='essay',blank_count=0)
            p.locator('#drawer header span').evaluate("e=>e.innerText='主观题作答'")
            p.locator('#drawer input').evaluate("e=>e.outerHTML='<textarea></textarea>'")
            r={**r,'suggested_answer':['主观题参考答案']}
    original=ElementHandle.scroll_into_view_if_needed
    def scroll(node,*args,**kwargs):
        if node.inner_text().strip()=='提交答案':raise TimeoutError('scroll wait timed out')
        return original(node,*args,**kwargs)
    monkeypatch.setattr(ElementHandle,'scroll_into_view_if_needed',scroll)
    assert '已填写并提交' in a.execute(w,d,r,lambda:None)
    assert p.evaluate('window.submits')==1
    with pytest.raises(AnswerStopped):a.execute(w,d,r,lambda:None)
    assert p.evaluate('window.submits')==1


def test_offscreen_submit_still_scrolls_before_click(scene,monkeypatch):
    p,w,a=scene;d,r=setup(p,w,'blank');trace=[];a.trace=lambda **kw:trace.append(kw)
    p.locator('.submit-btn').evaluate("e=>e.style.marginTop='2000px'")
    # Tabbing out of the final input focuses and scrolls to the button. Simulate
    # a classroom layout moving the viewport back before submission checks.
    original_step=a.step
    def step(name):
        original_step(name)
        if name=='提交前检查':p.evaluate('window.scrollTo(0,0)')
    monkeypatch.setattr(a,'step',step)
    assert '已填写并提交' in a.execute(w,d,r,lambda:None)
    assert p.evaluate('window.submits')==1
    assert any(t.get('phase')=='before_scroll' and not t['actionability']['visible'] for t in trace)
    assert any(t.get('phase')=='after_scroll' and t['actionability']['hit'] for t in trace)


def test_submit_covered_does_not_force_or_record_attempt(scene):
    p,w,a=scene;d,r=setup(p,w,'blank')
    p.locator('.submit-btn').evaluate("e=>{const b=e.getBoundingClientRect();const cover=document.createElement('div');cover.style=`position:fixed;left:${b.left}px;top:${b.top}px;width:${b.width}px;height:${b.height}px;z-index:10000;background:white`;document.body.appendChild(cover)}")
    with pytest.raises(AnswerStopped,match='提交按钮不可点击'):a.execute(w,d,r,lambda:None)
    assert p.evaluate('window.submits')==0 and not a.path.exists()
