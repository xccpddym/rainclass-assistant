import pytest
from rainclass.live import interpret, page_identity, LiveReadOnlyMonitor, LiveReadOnlyAdapter
from rainclass.browser import Browser,YuketangAdapter

URL='https://www.yuketang.cn/lesson/fullscreen/v3/123/exercise/8'
def evidence(timing='倒计时 04:28'):
    return {'wraps':[{'images':1,'submit':1,'timing':[timing],'option_labels':['A','B','C','D'],'text_fields':0}],
            'timeline_exercises':1,'visible_elements':100}

def test_closed_exercise_is_not_a_new_event():
    s=interpret(URL,evidence('作答已结束'))
    m=LiveReadOnlyMonitor()
    assert s['state']=='CLOSED_EXERCISE'
    assert m.observe(s) is None and not m.events

def test_active_repeated_observations_and_new_instance():
    m=LiveReadOnlyMonitor()
    s=interpret(URL,evidence())
    assert s['exercise']['remaining_seconds']==268
    assert m.observe(s)
    for _ in range(10):assert m.observe(interpret(URL,evidence('04:20'))) is None
    assert len(m.events)==1 and m.duplicates_suppressed==10
    assert m.observe(interpret(URL.replace('/8','/9'),evidence()))
    assert len(m.events)==2
    assert s['question'] is None and s['ai_allowed'] is False and s['submit_allowed'] is False

@pytest.mark.parametrize('timer',['未知','倒计时 04:99','还有 5 分钟','倒计时 --:--',''])
def test_unknown_or_invalid_timer_fails_closed(timer):
    s=interpret(URL,evidence(timer))
    assert s['state']=='NOT_VERIFIED'
    assert LiveReadOnlyMonitor().observe(s) is None

def test_ppt_and_sidebar_question_cannot_trigger():
    s=interpret(URL.replace('/exercise/','/ppt/'),evidence())
    assert s['state']=='IGNORE_PPT' and s['exercise'] is None

def test_observed_blank_route_does_not_need_opening_answer_editor():
    data=evidence();data['wraps'][0]['option_labels']=[]
    s=interpret(URL.replace('/exercise/','/blank/'),data)
    assert s['state']=='ACTIVE_EXERCISE' and s['exercise']['question_type']=='blank'
    assert s['question'] is None and s['submit_allowed'] is False

def test_observed_subjective_route_stays_read_only():
    data=evidence();data['wraps'][0]['option_labels']=[]
    s=interpret(URL.replace('/exercise/','/subjective/'),data)
    assert s['state']=='ACTIVE_EXERCISE' and s['exercise']['question_type']=='essay'
    assert s['question'] is None and s['ai_allowed'] is False


def test_subjective_editor_can_be_read_before_submit_control_mounts():
    data=evidence();w=data['wraps'][0];w.update(submit=0,text_fields=1)
    s=interpret(URL.replace('/exercise/','/subjective/'),data)
    assert s['state']=='ACTIVE_EXERCISE' and s['exercise']['question_type']=='essay'
    assert s['ai_allowed'] is False and s['submit_allowed'] is False
    # Missing editor or a choice route must still fail closed.
    assert interpret(URL,data)['state']=='NOT_VERIFIED'
    w['text_fields']=0
    assert interpret(URL.replace('/exercise/','/subjective/'),data)['state']=='NOT_VERIFIED'


@pytest.mark.parametrize('timer',['倒计时\n00 : 15','倒计时 00：15'])
def test_timer_with_layout_whitespace_or_fullwidth_colon(timer):
    s=interpret(URL,evidence(timer))
    assert s['state']=='ACTIVE_EXERCISE' and s['exercise']['remaining_seconds']==15


def test_waiting_diagnostics_contain_only_structure_not_question_text():
    s=interpret(URL,evidence('未知：题干不应进入诊断'))
    assert s['structure']['verification_reason']=='TIMER_FORMAT'
    assert s['structure']['image_count']==1 and s['structure']['submit_count']==1
    assert '题干' not in str(s['structure'])

@pytest.mark.parametrize('timer,seconds',[('00:00',0),('00:01',1),('倒计时 01:02:03',3723)])
def test_timer_boundary(timer,seconds):
    s=interpret(URL,evidence(timer))
    assert s['exercise']['remaining_seconds']==seconds
    assert s['exercise']['closed']==(seconds==0)

@pytest.mark.parametrize('field,value',[('images',0),('images',2),('submit',0),('timing',[]),('timing',['04:28','03:00'])])
def test_incomplete_or_ambiguous_container_fails_closed(field,value):
    data=evidence();data['wraps'][0][field]=value
    assert interpret(URL,data)['state']=='NOT_VERIFIED'

@pytest.mark.parametrize('url',[
 'http://www.yuketang.cn/lesson/fullscreen/v3/123/exercise/8',
 'https://www.yuketang.cn.example.com/lesson/fullscreen/v3/123/exercise/8',
 'https://name@www.yuketang.cn/lesson/fullscreen/v3/123/exercise/8',
 'https://www.yuketang.cn:444/lesson/fullscreen/v3/123/exercise/8',
 'https://www.yuketang.cn/v2/web/index'])
def test_host_and_route_boundaries(url):
    with pytest.raises(ValueError):page_identity(url)

def test_classroom_shell_is_not_a_question_even_with_stale_exercise_dom():
    url='https://www.yuketang.cn/lesson/fullscreen/v3/123'
    assert page_identity(url)==('123','pending','0')
    snapshot=interpret(url,evidence())
    assert snapshot['state']=='NOT_VERIFIED' and snapshot['exercise'] is None

def test_recovery_does_not_repeat_seen_instance():
    m=LiveReadOnlyMonitor();s=interpret(URL,evidence())
    assert m.observe(s)
    assert m.observe({'state':'RECOVERING'}) is None
    assert m.observe(s) is None
    assert len(m.events)==1

def test_live_adapter_has_no_submission_capability():
    assert not hasattr(LiveReadOnlyAdapter(),'submit')

def test_observed_dom_structure_with_real_edge(tmp_path):
    b=Browser(tmp_path/'rainclass-edge-profile')
    try:
        p=b.open('about:blank')
        class Page:
            url=URL
            def evaluate(self,script):return p.evaluate(script)
        html='''<div class="slide__cmp"><section class="slide__wrap">
        <img class="cover" style="width:100px;height:100px">
        <div class="time-box"><div class="timing">倒计时 04:28</div></div>
        <p class="options-label MultipleChoice">A</p><p class="options-label MultipleChoice">B</p>
        <div class="submit-btn">提交答案</div></section></div>'''
        p.set_content(html)
        s=LiveReadOnlyAdapter().snapshot(Page())
        assert s['state']=='ACTIVE_EXERCISE' and s['exercise']['option_count']==2
        routed=YuketangAdapter().snapshot(Page())
        assert routed['detection_status']=='ACTIVE_EXERCISE'
        assert routed['question'] is None and routed['ai_allowed'] is False
        # Visible evidence split between two containers must never be combined.
        p.set_content(html.replace('<div class="submit-btn">','</section><section class="slide__wrap"><div class="submit-btn">'))
        assert LiveReadOnlyAdapter().snapshot(Page())['state']=='NOT_VERIFIED'
        p.set_content('<div class="timeline__ppt problem">单选题 倒计时 提交答案</div><div class="slide__cmp"><section class="slide__wrap"><img class="cover" style="width:100px;height:100px"></section></div>')
        assert LiveReadOnlyAdapter().snapshot(Page())['state']=='NOT_VERIFIED'
        p.set_content(html.replace('倒计时 04:28','作答已结束'))
        assert LiveReadOnlyAdapter().snapshot(Page())['state']=='CLOSED_EXERCISE'
        p.set_content(html.replace('提交答案','作答'))
        class BlankPage(Page):url=URL.replace('/exercise/','/blank/')
        assert LiveReadOnlyAdapter().snapshot(BlankPage())['exercise']['question_type']=='blank'
    finally:b.close()


def test_subjective_visible_editor_same_container_without_submit_button(tmp_path):
    b=Browser(tmp_path/'rainclass-edge-profile')
    try:
        p=b.open('about:blank')
        class Page:
            url=URL.replace('/exercise/','/subjective/')
            def evaluate(self,script):return p.evaluate(script)
        html='''<div class="slide__cmp"><section class="slide__wrap">
          <img class="cover" width="100" height="80"><div class="time-box"><div class="timing">倒计时\n00 : 25</div></div>
          <div contenteditable="true">答题编辑器</div></section></div>'''
        p.set_content(html)
        s=LiveReadOnlyAdapter().snapshot(Page())
        assert s['state']=='ACTIVE_EXERCISE' and s['exercise']['question_type']=='essay'
        p.locator('[contenteditable]').evaluate("e=>e.style.display='none'")
        assert LiveReadOnlyAdapter().snapshot(Page())['state']=='NOT_VERIFIED'
    finally:b.close()
