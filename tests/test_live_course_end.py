"""The API reports class ended while its old page has no end message."""
import json
import pytest
from rainclass.browser import Browser
from rainclass.direct_discovery import DirectCourseDiscovery


@pytest.mark.parametrize('manual_recover',[False,True])
def test_worker_exits_unmarked_ended_course_without_reloading_it(monkeypatch,tmp_path,manual_recover):
    from PySide6.QtWidgets import QApplication
    from rainclass import real_worker
    app=QApplication.instance() or QApplication([])
    holder={};clock=[0];state={'active':True,'prepared':False};lesson_loads=[];statuses=[];reloads=[];closed=[]
    class OwnedBrowser(Browser):
        def __init__(self,profile,headless=False):super().__init__(profile,headless=True)
        def open(self,url):
            super().open('about:blank')
            def handle(route):
                if '/on-lesson' in route.request.url:
                    rows=[{'lessonId':'123','courseName':'测试'}] if state['active'] else []
                    route.fulfill(status=200,json={'data':{'onLessonClassrooms':rows}})
                elif '/lesson/' in route.request.url:
                    lesson_loads.append(route.request.url)
                    route.fulfill(status=200,content_type='text/html; charset=utf-8',body='''
                      <script>history.replaceState({},'', '/lesson/fullscreen/v3/123/blank/7')</script>
                      <div class="slide__cmp"><div class="slide__wrap"><img class="cover" width="50" height="40">
                      <div class="time-box"><div class="timing">倒计时 04:00</div></div><button class="submit-btn">作答</button></div></div>''')
                else:route.fulfill(status=200,body='<p>首页</p>')
            self.context.route('https://www.yuketang.cn/**',handle);self.page.goto(url)
            pump=self.page.wait_for_timeout
            def step(ms):
                clock[0]+=11
                if holder['worker'].monitor.events and not state['prepared']:
                    state['prepared']=True
                    self.context.new_page().goto('https://www.yuketang.cn/lesson/fullscreen/v3/123/blank/7')
                    state['active']=False
                    if manual_recover:holder['worker'].recover_request.set()
                if (tmp_path/'ended-lessons.json').exists():
                    closed.append(not any('/lesson/' in p.url for p in self.context.pages))
                    holder['worker'].stopping.set()
                if clock[0]>150:holder['worker'].stopping.set()
                pump(20)
            self.page.wait_for_timeout=step
            return self.page
    monkeypatch.setattr(real_worker,'Browser',OwnedBrowser)
    monkeypatch.setattr(real_worker,'DirectCourseDiscovery',lambda *a,**k:DirectCourseDiscovery(*a,**k,clock=lambda:clock[0]))
    worker=real_worker.RealWorker(tmp_path/'rainclass-edge-profile',tmp_path);holder['worker']=worker
    monkeypatch.setattr(worker,'_recover',lambda *a:reloads.append(True))
    worker.status.connect(lambda s:statuses.append(s['state']))
    worker.run()
    assert 'WAITING_FOR_CLASS' in statuses and len(worker.monitor.events)==1
    assert closed==[True] and len(lesson_loads)==2 and reloads==[]
    assert json.loads((tmp_path/'last-class-entry.json').read_text()) is None
    assert len(json.loads((tmp_path/'ended-lessons.json').read_text()))==1
