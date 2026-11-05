"""Real Edge actionability and bounded refresh recovery, all local DOM."""
import pytest
from rainclass.browser import Browser
from rainclass.follow import ExerciseFollower,click_failure
from rainclass.live import LiveReadOnlyAdapter
from tests.test_follow import classroom


def test_scrolled_timeline_clicks_latest_visible_region(classroom):
    page,poll,publish,clock,notices,follower=classroom
    page.add_style_tag(content='#timeline {height:70px;overflow-y:auto} #timeline a {display:block;height:45px}')
    poll()
    for event in range(2,20):publish(event)
    poll();poll()
    assert page.evaluate('window.eventId')==19
    assert page.evaluate("document.querySelector('#timeline').scrollTop")>0
    assert page.evaluate('window.answerClicks')==0


def test_obscured_target_refreshes_twice_then_normal_click(classroom):
    page,poll,publish,clock,notices,follower=classroom
    poll();publish(2)
    page.evaluate('''()=>{document.querySelector('#timeline').lastElementChild.removeAttribute('href');
      document.body.insertAdjacentHTML('beforeend','<div id="blocker" style="position:fixed;inset:0;z-index:999"></div>');
      window.healAfterReload=2;}''')
    for value in range(0,25,2):clock[0]=value;poll()
    assert page.evaluate('window.reloads')==2 and page.evaluate('window.eventId')==2
    assert page.evaluate('window.cardClicks')==1 and page.evaluate('window.answerClicks')==0
    assert follower.pending is None


def test_disable_or_newer_target_cancels_old_recovery(classroom):
    page,poll,publish,clock,notices,follower=classroom
    poll();page.evaluate('window.failClicks=true');publish(2)
    poll();poll(False)
    clock[0]=20;poll()
    assert page.evaluate('window.reloads||0')==0
    publish(3);poll();page.evaluate('window.failClicks=false');publish(4);poll();poll()
    assert page.evaluate('window.eventId')==4 and follower.pending is None


def test_pending_target_does_not_accept_wrong_exercise_route(classroom):
    page,poll,publish,clock,notices,follower=classroom
    poll();page.evaluate('window.failClicks=true');publish(3);poll()
    page.evaluate('window.eventId=2')
    assert poll() is True and follower.pending is not None
    page.evaluate('window.failClicks=false');clock[0]=2;poll();poll()
    assert page.evaluate('window.eventId')==3 and follower.pending is None


def test_animation_wait_does_not_force_click(classroom):
    page,poll,publish,clock,notices,follower=classroom
    poll();publish(2)
    page.add_style_tag(content='@keyframes moving {from{transform:translateX(0)}to{transform:translateX(50px)}} [data-event-id="2"] {display:block;animation:moving .5s linear infinite}')
    poll();assert follower.diagnostics['click_reason']=='ANIMATING'
    assert page.evaluate('window.cardClicks')==0
    page.evaluate("document.querySelector('[data-event-id=\"2\"]').style.animation='none'")
    clock[0]=2;poll();poll()
    assert page.evaluate('window.eventId')==2 and page.evaluate('window.cardClicks')==1


def test_replaced_node_is_relocated_instead_of_clicking_another_card(classroom,monkeypatch):
    from playwright.sync_api import ElementHandle
    page,poll,publish,clock,notices,follower=classroom
    poll();publish(2);scroll=ElementHandle.scroll_into_view_if_needed;replaced=[]
    def replace_once(node,**kwargs):
        if not replaced:
            replaced.append(True)
            node.evaluate('e=>{const n=e.cloneNode(true);n.onclick=e.onclick;e.replaceWith(n)}')
        return scroll(node,**kwargs)
    monkeypatch.setattr(ElementHandle,'scroll_into_view_if_needed',replace_once)
    poll();assert follower.diagnostics['click_reason']=='DETACHED'
    clock[0]=2;poll();poll()
    assert page.evaluate('window.eventId')==2 and page.evaluate('window.answerClicks')==0


def test_new_publication_supersedes_refreshing_target(classroom):
    page,poll,publish,clock,notices,follower=classroom
    poll();publish(2)
    page.evaluate('''()=>{document.querySelector('#timeline').lastElementChild.removeAttribute('href');
      document.body.insertAdjacentHTML('beforeend','<div id="blocker" style="position:fixed;inset:0;z-index:999"></div>')}''')
    for value in (0,2,4,6):clock[0]=value;poll()
    assert page.evaluate('window.reloads')==1
    page.evaluate("document.querySelector('#blocker').remove()");publish(3)
    clock[0]=8;poll();poll()
    assert page.evaluate('window.eventId')==3 and page.evaluate('window.reloads')==1
    assert follower.pending is None


@pytest.mark.parametrize('limit',[0,1,3,5])
def test_configured_refresh_limit_preserves_time_budget(classroom,limit):
    page,poll,publish,clock,notices,follower=classroom
    follower.max_refreshes=limit;poll();publish(2)
    page.evaluate('''()=>{document.querySelector('#timeline').lastElementChild.removeAttribute('href');
      document.body.insertAdjacentHTML('beforeend','<div style="position:fixed;inset:0;z-index:999"></div>')}''')
    for value in range(0,45,2):clock[0]=value;poll()
    assert page.evaluate('window.reloads||0')==limit
    assert follower.pending is None and page.evaluate('window.cardClicks')==0


@pytest.mark.parametrize('message,reason',[
    ('element intercepts pointer events','OBSCURED'),('element is not stable','ANIMATING'),
    ('Element is outside of the viewport','OFFSCREEN'),('not visible','NOT_VISIBLE'),
    ('not enabled','DISABLED'),('Element is detached','DETACHED')])
def test_actionability_error_saved_as_enum_without_page_text(message,reason):
    assert click_failure(RuntimeError(message+' PRIVATE URL AND TEXT'))==reason


@pytest.mark.parametrize('mode',['exercise','blank','subjective'])
def test_real_document_reload_recovers_obscured_card(tmp_path,mode):
    browser=Browser(tmp_path/'rainclass-edge-profile',headless=True)
    loads=[];notices=[];clock=[0]
    follower=ExerciseFollower(notices.append,clock=lambda:clock[0]);adapter=LiveReadOnlyAdapter()
    base='https://www.yuketang.cn/lesson/fullscreen/v3/123'
    def route(r):
        loads.append(r.request.url)
        # First load and first reload remain obstructed; second reload heals.
        overlay='<div id="blocker" style="position:fixed;inset:0;z-index:999"></div>' if len(loads)<3 else ''
        r.fulfill(status=200,content_type='text/html; charset=utf-8',body=f'''
          <script>window.answerClicks=0;window.cardClicks=0</script>
          <div id="timeline"><a class="timeline__ppt problem" data-event-id="1">旧题</a></div>
          <div class="slide__cmp"><section class="slide__wrap"><img class="cover" width="50" height="50">
          <div class="time-box"><div class="timing">00:40</div></div>
          <button class="submit-btn" onclick="window.answerClicks++">作答</button></section></div>{overlay}
          <script>window.install=()=>{{const a=document.createElement('a');a.className='timeline__ppt problem';a.dataset.eventId='2';
            a.textContent='新题';a.onclick=()=>{{window.cardClicks++;history.replaceState({{}},'', '{base}/{mode}/2')}};
            document.querySelector('#timeline').append(a)}};
          if(sessionStorage.getItem('published'))window.install();</script>''')
    try:
        browser.open('about:blank');browser.context.route('https://www.yuketang.cn/**',route)
        page=browser.page;page.goto(base+'/ppt/1');follower.poll(page,adapter.snapshot(page))
        page.evaluate("sessionStorage.setItem('published','1');window.install()")
        for value in range(0,25,2):
            clock[0]=value;follower.poll(page,adapter.snapshot(page))
        assert len(loads)==3 and page.url==base+'/'+mode+'/2'
        assert follower.pending is None and page.evaluate('window.cardClicks')==1
        assert page.evaluate('window.answerClicks')==0
    finally:browser.close()
