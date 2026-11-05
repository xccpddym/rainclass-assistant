"""Real Edge DOM tests: timeline publication does not itself change the main slide."""
import pytest
from rainclass.browser import Browser
from rainclass.follow import ExerciseFollower
from rainclass.live import LiveReadOnlyAdapter

@pytest.fixture
def classroom(tmp_path):
    browser=Browser(tmp_path/'rainclass-edge-profile',headless=True)
    page=browser.open('about:blank')
    page.set_content('''<script>window.eventId=1;window.mode='exercise';window.answerClicks=0;window.cardClicks=0;window.failClicks=false;</script>
      <div id="timeline"><a class="timeline__ppt problem" data-event-id="1"
      href="https://www.yuketang.cn/lesson/fullscreen/v3/123/exercise/1"
      onclick="event.preventDefault();window.cardClicks++;if(!window.failClicks)window.eventId=1">旧题</a></div>
      <div class="slide__cmp"><div class="slide__wrap"><img class="cover" width="40" height="40">
      <div class="time-box"><div class="timing">倒计时 04:00</div></div>
      <button class="submit-btn" onclick="window.answerClicks++">提交答案</button>
      <input onclick="window.answerClicks++"></div></div>''')
    class Page:
        @property
        def url(self):return 'https://www.yuketang.cn/lesson/fullscreen/v3/123/'+page.evaluate('window.mode')+'/'+str(page.evaluate('window.eventId'))
        def locator(self,*a,**k):return page.locator(*a,**k)
        def evaluate(self,*a,**k):return page.evaluate(*a,**k)
        def goto(self,url,**kwargs):
            if page.evaluate('!!window.failNavigation'):raise RuntimeError('navigation unavailable')
            from rainclass.live import page_identity
            _,mode,event=page_identity(url)
            page.evaluate('({mode,event})=>{window.mode=mode;window.eventId=Number(event);window.directOpens=(window.directOpens||0)+1}',{'mode':mode,'event':event})
        def reload(self,**kwargs):
            page.evaluate('''()=>{window.reloads=(window.reloads||0)+1;
              if(window.healAfterReload && window.reloads>=window.healAfterReload){
                window.failClicks=false;document.querySelector('#blocker')?.remove();
              }}''')
    wrapped=Page();adapter=LiveReadOnlyAdapter();notices=[];clock=[0]
    follower=ExerciseFollower(notices.append,clock=lambda:clock[0])
    def poll(enabled=True):return follower.poll(wrapped,adapter.snapshot(wrapped),enabled)
    def publish(event,replace=False,href=None):
        page.evaluate('''({event,replace,href})=>{
          const card=document.createElement('a');card.className='timeline__ppt problem';
          card.dataset.eventId=String(event);card.href=href||'https://www.yuketang.cn/lesson/fullscreen/v3/123/exercise/'+event;
          card.textContent='相同题干 倒计时 04:00';
          card.onclick=e=>{e.preventDefault();window.cardClicks++;if(!window.failClicks){window.eventId=event;window.mode='exercise';}};
          const list=document.querySelector('#timeline');if(replace)list.replaceChildren(card);else list.append(card);
        }''',{'event':event,'replace':replace,'href':href})
    yield page,poll,publish,clock,notices,follower
    browser.close()

def test_new_card_follows_from_stale_main_and_same_count_replacement(classroom):
    page,poll,publish,clock,notices,follower=classroom
    assert poll() is False and page.evaluate('window.cardClicks')==0
    publish(2)
    assert page.evaluate('window.eventId')==1
    assert poll() is True  # click alone is not a verified success
    assert poll() is False and page.evaluate('window.eventId')==2
    for _ in range(3):assert poll() is False
    assert page.evaluate('window.cardClicks')==1
    # Replace the list without changing its length, then publish the same text again.
    publish(3,replace=True);poll();poll()
    publish(4,replace=True);poll();poll()
    assert page.evaluate('window.eventId')==4
    assert page.evaluate('window.cardClicks')==3 and page.evaluate('window.answerClicks')==0

def test_retry_limit_superseded_target_and_disabled_follow(classroom):
    page,poll,publish,clock,notices,follower=classroom
    poll();page.evaluate('window.failClicks=true');publish(2)
    for value in (0,3,6,9,12,15):clock[0]=value;poll()
    assert page.evaluate('window.cardClicks')==3
    assert page.evaluate('window.directOpens')==1
    assert page.evaluate('window.eventId')==2
    publish(3);poll()  # new target receives its own retry budget
    page.evaluate('window.failClicks=false');publish(4);poll();poll()
    assert page.evaluate('window.eventId')==4
    clicks=page.evaluate('window.cardClicks')
    publish(5);assert poll(False) is False
    assert poll(True) is False and page.evaluate('window.cardClicks')==clicks
    assert page.evaluate('window.answerClicks')==0

def test_list_reorder_countdown_and_unsafe_link_do_not_navigate(classroom):
    page,poll,publish,clock,notices,follower=classroom
    poll();publish(2);poll();poll()
    clicks=page.evaluate('window.cardClicks')
    page.evaluate("document.querySelector('#timeline').prepend(document.querySelector('#timeline').lastElementChild)")
    page.evaluate("document.querySelector('#timeline').firstElementChild.textContent='相同题干 倒计时 03:59'")
    assert poll() is False and page.evaluate('window.cardClicks')==clicks
    publish(3,href='https://example.com/')
    assert poll() is False and page.evaluate('window.cardClicks')==clicks
    assert any('链接无法确认' in n for n in notices)

def test_follow_from_ppt_and_stable_identity_survives_card_rerender(classroom):
    page,poll,publish,clock,notices,follower=classroom
    page.evaluate("window.mode='ppt'");poll()
    publish(2);assert poll() is True
    assert poll() is False and page.evaluate('window.mode')=='exercise'
    clicks=page.evaluate('window.cardClicks')
    page.evaluate("document.querySelector('#timeline').lastElementChild.textContent='更新后的展示文字'")
    assert poll() is False and page.evaluate('window.cardClicks')==clicks

def test_unanswered_and_expired_cards_do_not_block_latest_batch(classroom):
    page,poll,publish,clock,notices,follower=classroom
    poll()
    page.evaluate("document.querySelector('#timeline a').textContent='旧题 未作答'")
    publish(2);publish(3)
    poll();poll()
    assert page.evaluate('window.eventId')==3
    assert page.evaluate('window.cardClicks')==1
    page.evaluate("document.querySelector('#timeline a').textContent='旧题 已超时'")
    assert poll() is False
    publish(4);poll();poll()
    assert page.evaluate('window.eventId')==4
    assert page.evaluate('window.answerClicks')==0
    assert not any('手动选择最新题' in n for n in notices)

def test_status_only_identity_and_identical_image_republication(classroom):
    page,poll,publish,clock,notices,follower=classroom
    page.evaluate("const a=document.querySelector('#timeline a');a.removeAttribute('href');a.removeAttribute('data-event-id');a.textContent='旧题 未作答';")
    poll()
    page.evaluate("document.querySelector('#timeline a').textContent='旧题 已超时'")
    assert poll() is False and page.evaluate('window.cardClicks')==0
    # Two new image cards arrive together; the old unanswered card stays in place.
    for event in (2,3):
        publish(event)
    page.evaluate("for(const a of document.querySelectorAll('#timeline a:not(:first-child)')){a.removeAttribute('href');a.removeAttribute('data-event-id');a.innerHTML='<img src=\"data:,same-slide\">未作答';}")
    poll();poll()
    assert page.evaluate('window.eventId')==3
    page.evaluate("document.querySelector('#timeline a:nth-child(2)').lastChild.textContent='已超时'")
    assert poll() is False
    assert page.evaluate('window.cardClicks')==1 and page.evaluate('window.answerClicks')==0

def test_expired_old_question_new_route_loading_does_not_reclick(classroom):
    page,poll,publish,clock,notices,follower=classroom
    poll();page.evaluate("document.querySelector('.timing').textContent='作答已结束'")
    publish(2);poll()
    assert page.evaluate('window.eventId')==2
    page.evaluate("document.querySelector('.time-box').remove()")
    for value in (1,4,7,10):
        clock[0]=value
        assert poll() is False
    assert page.evaluate('window.cardClicks')==1
    page.evaluate("document.querySelector('.slide__wrap').insertAdjacentHTML('beforeend','<div class=\"time-box\"><div class=\"timing\">倒计时 00:30</div></div>')")
    publish(3);poll();poll()
    assert page.evaluate('window.eventId')==3 and page.evaluate('window.answerClicks')==0

def test_javascript_placeholder_link_does_not_hide_new_card_identity(classroom):
    page,poll,publish,clock,notices,follower=classroom
    page.evaluate("document.querySelector('#timeline a').setAttribute('href','javascript:void(0)')")
    poll();publish(2)
    page.evaluate("document.querySelector('#timeline').lastElementChild.setAttribute('href','javascript:void(0)')")
    poll();poll()
    assert page.evaluate('window.eventId')==2
    assert not any('链接无法确认' in n for n in notices)


def test_card_ppt_href_but_handler_opens_exercise_is_confirmed(classroom):
    page,poll,publish,clock,notices,follower=classroom
    poll();publish(2,href='https://www.yuketang.cn/lesson/fullscreen/v3/123/ppt/22')
    assert poll() is True
    assert poll() is False
    for value in (3,6,9,12):clock[0]=value;poll()
    assert page.evaluate('window.cardClicks')==1
    assert not any('停止重试' in n for n in notices)


def test_new_card_link_to_old_route_still_requires_click(classroom):
    page,poll,publish,clock,notices,follower=classroom
    poll();publish(2,href='https://www.yuketang.cn/lesson/fullscreen/v3/123/exercise/1')
    assert poll() is True
    assert poll() is False
    assert page.evaluate('window.eventId')==2
    assert page.evaluate('window.cardClicks')==1


def test_card_href_rerender_with_same_id_does_not_follow_old_card(classroom):
    page,poll,publish,clock,notices,follower=classroom
    poll();publish(2);poll();poll()
    page.evaluate("document.querySelector('#timeline a').href='https://www.yuketang.cn/lesson/fullscreen/v3/123/exercise/99'")
    assert poll() is False
    assert page.evaluate('window.eventId')==2


def test_failed_click_and_failed_fallback_are_bounded(classroom):
    page,poll,publish,clock,notices,follower=classroom
    poll();page.evaluate('window.failClicks=true;window.failNavigation=true');publish(2)
    for value in (0,3,6,9,14,20,25,30,35,40,45):clock[0]=value;poll()
    assert not follower.pending
    assert page.evaluate('window.cardClicks')<=9
    assert page.evaluate('window.reloads')==2
    assert sum('停止重试' in n or '停止自动操作' in n for n in notices)==1
    assert page.evaluate('window.answerClicks')==0


def test_late_old_thumbnail_does_not_navigate_back_from_new_question(classroom):
    page,poll,publish,clock,notices,follower=classroom
    page.evaluate("const a=document.querySelector('#timeline a');a.removeAttribute('href');a.removeAttribute('data-event-id');a.innerHTML='<img src=\"data:,loading\">';")
    poll();publish(2);poll();poll()
    page.evaluate("document.querySelector('#timeline img').src='data:,loaded-old-thumbnail'")
    assert poll() is False
    assert page.evaluate('window.eventId')==2 and page.evaluate('window.cardClicks')==1


def test_loading_route_falls_back_to_ppt_and_retries_without_reclick_during_load(classroom):
    page,poll,publish,clock,notices,follower=classroom
    poll();publish(2);poll()
    page.evaluate("document.querySelector('.time-box').remove()")
    clock[0]=1;assert poll() is False
    assert follower.pending and page.evaluate('window.cardClicks')==1
    page.evaluate("window.mode='ppt';window.eventId=1")
    clock[0]=3;assert poll() is True
    assert page.evaluate('window.eventId')==2 and page.evaluate('window.cardClicks')==2
    page.evaluate("document.querySelector('.slide__wrap').insertAdjacentHTML('beforeend','<div class=\"time-box\"><div class=\"timing\">00:25</div></div>')")
    assert poll() is False and follower.pending is None
    assert page.evaluate('window.answerClicks')==0


def test_auto_opened_subjective_is_not_blocked_waiting_for_another_route_change(classroom):
    page,poll,publish,clock,notices,follower=classroom
    poll();publish(2,href='https://www.yuketang.cn/lesson/fullscreen/v3/123/subjective/2')
    page.evaluate("window.eventId=2;window.mode='subjective'")
    assert poll() is False
    assert follower.pending is None and page.evaluate('window.cardClicks')==0
    assert follower.diagnostics['phase']=='VERIFIED'


def test_auto_opened_question_loading_never_restarts_image_load(classroom):
    page,poll,publish,clock,notices,follower=classroom
    poll();publish(2);page.evaluate("window.eventId=2;document.querySelector('.time-box').remove()")
    for value in (1,4,7):
        clock[0]=value;assert poll() is False
    assert page.evaluate('window.cardClicks')==0 and follower.pending is not None
    page.evaluate("document.querySelector('.slide__wrap').insertAdjacentHTML('beforeend','<div class=\"time-box\"><div class=\"timing\">00:10</div></div>')")
    assert poll() is False and follower.pending is None


def test_different_target_is_still_clicked_when_another_route_auto_opens(classroom):
    page,poll,publish,clock,notices,follower=classroom
    poll();publish(3);page.evaluate('window.eventId=2')
    assert poll() is True
    assert page.evaluate('window.eventId')==3 and page.evaluate('window.cardClicks')==1
