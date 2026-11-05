from threading import Event
import hashlib
import pytest
from rainclass.browser import Browser
from rainclass.direct_discovery import DirectCourseDiscovery
from rainclass.discovery import HOME

@pytest.mark.parametrize('rows,enabled,preferred,state',[
    ([],True,'','WAITING_FOR_CLASS'),
    ([{'lessonId':'91','courseName':'课程甲'}],True,'','ENTERING_CLASS'),
    ([{'lessonId':'91','courseName':'课程甲'}],False,'','AUTO_ENTER_DISABLED'),
    ([{'lessonId':'91','courseName':'甲'},{'lessonId':'92','courseName':'乙'}],True,'','COURSE_CHOICE_REQUIRED'),
    ([{'lessonId':'91','courseName':'甲'},{'lessonId':'92','courseName':'乙'}],True,'乙','ENTERING_CLASS'),
])
def test_direct_query_never_opens_course_details(tmp_path,rows,enabled,preferred,state):
    browser=Browser(tmp_path/'rainclass-edge-profile');browser.open('about:blank');requests=[]
    def route(r):
        requests.append((r.request.method,r.request.url))
        if '/on-lesson' in r.request.url:r.fulfill(status=200,json={'data':{'onLessonClassrooms':rows}})
        else:r.fulfill(status=200,content_type='text/html; charset=utf-8',body='<p>课程首页</p>')
    browser.context.route('https://www.yuketang.cn/**',route)
    try:
        browser.page.goto(HOME);clock=[0];ended=set();stop=Event()
        d=DirectCourseDiscovery(lambda t:None,ended,stop,clock=lambda:clock[0])
        assert d.tick(browser.context,enabled,preferred)==state
        assert d.login_state=='SIGNED_IN' and d.last_query_at is not None
        assert all('/studentLog/' not in url for _,url in requests)
        assert all(method=='GET' for method,_ in requests)
        if state=='ENTERING_CLASS':
            chosen='92' if preferred=='乙' else '91'
            assert any(url.endswith('/v3/'+chosen) for _,url in requests)
        # Idle polling changes no page, and is rate limited.
        initial=len(requests);d.tick(browser.context,False,preferred)
        assert len(requests)==initial
        for page in list(browser.context.pages):
            if '/lesson/' in page.url:page.close()
        ended.update(hashlib.sha256(str(row['lessonId']).encode()).hexdigest() for row in rows)
        clock[0]=11
        assert d.tick(browser.context,True,preferred)=='WAITING_FOR_CLASS'
        assert not any('/lesson/' in p.url for p in browser.context.pages)
    finally:browser.close()

@pytest.mark.parametrize('status,payload,expected',[(401,None,'LOGIN_REQUIRED'),(403,None,'LOGIN_REQUIRED'),(200,{},'NOT_VERIFIED'),(500,None,'NOT_VERIFIED')])
def test_query_error_never_falls_back_to_course_clicks(tmp_path,status,payload,expected):
    b=Browser(tmp_path/'rainclass-edge-profile');b.open('about:blank');paths=[]
    def route(r):
        paths.append(r.request.url)
        if '/on-lesson' in r.request.url:r.fulfill(status=status,json=payload or {})
        else:r.fulfill(status=200,body='<p>home</p>')
    b.context.route('https://www.yuketang.cn/**',route)
    try:
        b.page.goto(HOME);d=DirectCourseDiscovery(lambda t:None,set(),Event())
        assert d.tick(b.context,True)==expected
        assert len(b.context.pages)==1
        assert not any('/studentLog/' in p for p in paths)
    finally:b.close()


def test_live_course_checks_confirm_absence_and_reset_on_error():
    clock=[0];calls=[]
    class Page:
        url='https://www.yuketang.cn/lesson/fullscreen/v3/123/blank/7'
        data={'state':'OK','lessons':[{'id':'123','course':'课堂'}]}
        def evaluate(self,script):calls.append(script);return self.data
    p=Page();d=DirectCourseDiscovery(lambda t:None,set(),Event(),clock=lambda:clock[0])
    assert d.check_current(p) is True
    assert d.check_current(p) is None and len(calls)==1
    clock[0]=10;p.data={'state':'OK','lessons':[]}
    assert d.check_current(p) is None
    clock[0]=20;p.data={'state':'NOT_VERIFIED'}
    assert d.check_current(p) is None and d.live_missing==0
    clock[0]=30;p.data={'state':'OK','lessons':[{'id':'999','course':'下一节'}]}
    assert d.check_current(p) is None
    assert d.check_current(p,force=True) is False
    assert d.active==[{'lesson':'999','course':'下一节'}]
    p.data={'state':'LOGIN_REQUIRED'}
    assert d.check_current(p,force=True) is None and d.live_missing==0
    assert d.login_state=='LOGIN_REQUIRED'
    p.data={'state':'OK','lessons':[{'id':'invalid'}]}
    assert d.check_current(p,force=True) is None and d.live_missing==0


def test_transient_missing_current_lesson_does_not_end_class():
    class Page:
        url='https://www.yuketang.cn/lesson/fullscreen/v3/123/ppt/1'
        data={'state':'OK','lessons':[]}
        def evaluate(self,script):return self.data
    p=Page();d=DirectCourseDiscovery(lambda t:None,set(),Event())
    assert d.check_current(p,force=True) is None
    p.data={'state':'OK','lessons':[{'id':'123'}]}
    assert d.check_current(p,force=True) is True and d.live_missing==0
    p.data={'state':'OK','lessons':[]}
    assert d.check_current(p,force=True) is None
