from rainclass.browser import Browser
from rainclass.discovery import CourseDiscovery
from tests.test_lifecycle import install_routes

def test_ended_record_is_not_reentered_but_next_lesson_can_enter(tmp_path):
    b=Browser(tmp_path/'rainclass-edge-profile');b.open('about:blank')
    install_routes(b.context)
    entry={'course':'课程0','url':'https://www.yuketang.cn/v2/web/studentLog/0'}
    clock=[0];blocked=set();d=CourseDiscovery(lambda t:None,resume=entry,blocked=blocked,clock=lambda:clock[0])
    try:
        b.page.goto(entry['url']);d.tick(b.context,True);b.page.wait_for_timeout(100)
        d._enter(b.context)
        assert d.last_entry==entry
        d.mark_ended()
        assert blocked and d.last_entry is None and d.resume_hint is None
        assert d.tick(b.context,True)=='WAITING_FOR_CLASS'
        for p in list(b.context.pages):
            if '/lesson/' in p.url:p.close()
        # Even if the server leaves the old "正在上课" card behind, do not click it.
        clock[0]=31;b.page.goto(entry['url'])
        restored=CourseDiscovery(lambda t:None,blocked=set(blocked),clock=lambda:clock[0])
        restored.page=b.page;restored.phase='resume';restored.names=['课程0']
        restored.tick(b.context,True);b.page.wait_for_timeout(50)
        assert not any('/lesson/' in p.url for p in b.context.pages)
        # A new visible record in that same course is a new lesson, not a ban on the course.
        b.page.goto(entry['url'])
        b.page.evaluate("const card=document.querySelector('.studentCard');card.append(' 第二节 2026-11-04 09:00');card.querySelector('h2').onclick=()=>window.open('/lesson/fullscreen/v3/999/ppt/1')")
        restored.page=b.page;restored.phase='resume';restored.names=['课程0'];restored.index=0;restored.active=[];restored.ready_since=None
        restored.tick(b.context,True);b.page.wait_for_timeout(100)
        assert any('/v3/999/' in p.url for p in b.context.pages)
    finally:b.close()
