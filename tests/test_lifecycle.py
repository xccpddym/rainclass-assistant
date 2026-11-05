import ctypes
import json
from pathlib import Path
import pytest
from rainclass.browser import Browser
from rainclass.discovery import CourseDiscovery,HOME

def install_routes(context,count=1,active=True):
    def handle(route):
        url=route.request.url
        if '/api/v3/classroom/on-lesson' in url:
            route.fulfill(status=200,json={'data':{'onLessonClassrooms':[{'lessonId':str(123+i),'courseName':f'课程{i}'} for i in range(count)] if active else []}});return
        import re
        if '/lesson/' in url:
            html='''<div class="slide__cmp"><div class="slide__wrap"><img class="cover" width="50" height="40">
                <div class="time-box"><div class="timing">倒计时 04:00</div></div><div class="submit-btn">作答</div></div></div>'''
            if re.search(r'/lesson/fullscreen/v3/\d+$',url):html+="<script>history.replaceState({},'',location.pathname+'/blank/7')</script>"
        elif '/studentLog/' in url:
            html='<div class="classroom-header-base">课程</div>'
            if active:html+='''<div class="logs-list"><div class="studentCard">正在上课<h2 onclick="window.open('/lesson/fullscreen/v3/123/blank/7')">测试课堂</h2></div></div>'''
        else:
            html='<div class="index__view"><div class="el-tabs__item is-active">我听的课</div>'
            html+=''.join(f'<div class="el-card box-card"><h1 onclick="location.href=\'/v2/web/studentLog/{i}\'">课程{i}</h1></div>' for i in range(count))+'</div>'
        route.fulfill(status=200,content_type='text/html; charset=utf-8',body=html)
    context.route('https://www.yuketang.cn/**',handle)

@pytest.mark.parametrize('count,enabled,preferred,expected',[(1,True,'','ENTERING_CLASS'),(0,True,'','WAITING_FOR_CLASS'),(2,True,'','COURSE_CHOICE_REQUIRED'),(2,True,'课程1','ENTERING_CLASS'),(1,False,'','WAITING_FOR_CLASS')])
def test_discovery_with_real_edge(tmp_path,count,enabled,preferred,expected):
    b=Browser(tmp_path/'rainclass-edge-profile');b.open('about:blank')
    try:
        install_routes(b.context,count);b.page.goto(HOME)
        clock=[0];d=CourseDiscovery(lambda text:None,clock=lambda:clock[0])
        for _ in range(2*count+8):
            clock[0]+=1
            state=d.tick(b.context,enabled,preferred)
            if state!='DISCOVERING':break
        assert state==expected
        if expected=='ENTERING_CLASS':
            b.page.wait_for_timeout(100)
            assert any('/lesson/' in p.url for p in b.context.pages)
    finally:b.close()

@pytest.mark.parametrize('failure',['window_close','process_crash','stop','course_end','repeated_close'])
@pytest.mark.parametrize('silent',[False,True])
def test_worker_restarts_and_preserves_dedupe(monkeypatch,tmp_path,failure,silent):
    from PySide6.QtWidgets import QApplication
    from rainclass import real_worker
    app=QApplication.instance() or QApplication([])
    launches=[];signals=[];holder={};iterations=[0];focus=[];focus_pids=[];states=[];ended=[False]
    fg=ctypes.windll.user32.GetForegroundWindow
    before=fg()
    class OwnedBrowser(Browser):
        def __init__(self,profile,headless=False):
            # Local verification is headless, including its first launch.
            launches.append(headless);super().__init__(profile,headless=True)
        def open(self,url):
            super().open('about:blank');install_routes(self.context)
            self.page.goto(HOME)
            baseline=holder['worker'].monitor.duplicates_suppressed
            real=self.page.wait_for_timeout
            def pump(ms):
                iterations[0]+=1;focus.append(fg())
                pid=ctypes.c_ulong();ctypes.windll.user32.GetWindowThreadProcessId(focus[-1],ctypes.byref(pid));focus_pids.append(pid.value)
                if iterations[0]>30:holder['worker'].stopping.set();return
                if len(holder['worker'].monitor.events)==1:
                    if failure=='repeated_close':
                        if len(launches)>1 and holder['worker'].monitor.duplicates_suppressed<=baseline:
                            real(20);return
                        if len(launches)<=7:self.context.close()
                        else:holder['worker'].stopping.set()
                        return
                    if len(launches)==1:
                        if failure=='course_end':
                            live=[p for p in self.context.pages if '/lesson/' in p.url]
                            if not live and ended[0]:holder['worker'].stopping.set();return
                            for p in live:p.set_content('<p> 本次课程已经结束，请退出课堂。 </p><footer>雨课堂</footer>')
                            ended[0]=True;return
                        if failure=='stop':holder['worker'].stopping.set();return
                        if failure=='window_close':self.context.close()
                        else:
                            import subprocess,os
                            script="Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'msedge.exe' -and $_.CommandLine -and $_.CommandLine.Contains($env:RAINCLASS_TEST_PROFILE) -and $_.CommandLine -notmatch '--type=' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
                            subprocess.run(['powershell','-NoProfile','-Command',script],env={**os.environ,'RAINCLASS_TEST_PROFILE':str(self.profile)},check=True,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
                        return
                    if holder['worker'].monitor.duplicates_suppressed:
                        holder['worker'].stopping.set();return
                real(20)
            self.page.wait_for_timeout=pump
            return self.page
    monkeypatch.setattr(real_worker,'Browser',OwnedBrowser)
    monkeypatch.setattr(real_worker,'recognize_question',lambda *a:{'text':'题干','stem':'题干','options':[],'kind_hint':'blank'})
    worker=real_worker.RealWorker(tmp_path/'rainclass-edge-profile',tmp_path)
    if silent:worker.silent_recovery.set()
    holder['worker']=worker
    worker.new_question.connect(signals.append)
    worker.status.connect(lambda state:states.append(state['state']))
    worker.run()
    assert len(worker.monitor.events)==1 and len(signals)==1
    assert (tmp_path/'discovery-state.json').is_file()
    assert len(launches)==(8 if failure=='repeated_close' else 1 if failure in ('stop','course_end') else 2)
    if failure in ('window_close','process_crash','repeated_close'):
        assert launches[1] is silent
        assert worker.monitor.duplicates_suppressed>=1
    assert iterations[0]<=30
    if failure=='course_end':
        assert 'WAITING_FOR_CLASS' in states
        assert json.loads((tmp_path/'last-class-entry.json').read_text()) is None
        assert json.loads((tmp_path/'ended-lessons.json').read_text())
    # The user may switch their own foreground app during this integration test.
    # Headless Edge has no window; a changed foreground must not be this Qt process.
    import os
    assert all(h==before or pid!=os.getpid() for h,pid in zip(focus,focus_pids))
    rows=[json.loads(line) for line in (tmp_path/'browser-recovery.jsonl').read_text().splitlines()]
    assert any(r['event']=='connected' for r in rows)

@pytest.mark.parametrize('stop_in_backoff',[False,True])
def test_recovery_budget_and_interruptible_stop(monkeypatch,tmp_path,stop_in_backoff):
    from rainclass import real_worker
    calls=[]
    class FailingBrowser:
        def __init__(self,*a,**k):calls.append(k['headless'])
        def open(self,url):raise ConnectionError('test')
        def close(self):pass
    class Stop:
        stopped=False
        def is_set(self):return self.stopped
        def wait(self,seconds):
            self.stopped=stop_in_backoff
            return self.stopped
    monkeypatch.setattr(real_worker,'Browser',FailingBrowser)
    worker=real_worker.RealWorker(tmp_path/'rainclass-edge-profile',tmp_path)
    worker.stopping=Stop();worker.run()
    assert len(calls)==(1 if stop_in_backoff else 6)
    assert not any(calls)

def test_expired_login_no_course_and_observer_reinstalled(tmp_path):
    b=Browser(tmp_path/'rainclass-edge-profile');b.open('about:blank')
    try:
        install_routes(b.context,active=False);b.page.goto(HOME)
        clock=[0];d=CourseDiscovery(lambda text:None,clock=lambda:clock[0])
        for _ in range(8):
            clock[0]+=1;state=d.tick(b.context,True)
            if state=='WAITING_FOR_CLASS':break
        assert state=='WAITING_FOR_CLASS'
        d.next_at=0;b.page.set_content('<p>请扫码登录</p>')
        assert d.tick(b.context,True)=='LOGIN_REQUIRED'
        p=b.context.new_page();p.goto(HOME)
        assert p.evaluate('typeof window.__rainRevision')=='number'
        p.evaluate("document.body.append(document.createElement('p'))")
        p.wait_for_timeout(20)
        assert p.evaluate('window.__rainRevision')>0
    finally:b.close()
