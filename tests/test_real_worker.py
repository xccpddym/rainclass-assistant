"""Exercise the production read-only worker with real Edge and local DOM fixtures."""
import base64
import time
from rainclass.browser import Browser

def test_worker_edges_ocr_and_real_submission_boundary(monkeypatch,tmp_path):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage
    from PySide6.QtCore import QBuffer,QIODevice
    from rainclass import real_worker
    app=QApplication.instance() or QApplication([])
    image=QImage(400,200,QImage.Format.Format_RGB32);image.fill(0xffffffff)
    buffer=QBuffer();buffer.open(QIODevice.OpenModeFlag.WriteOnly);image.save(buffer,'PNG')
    uri='data:image/png;base64,'+base64.b64encode(bytes(buffer.data())).decode()
    observations=[];previews=[];notices=[];messages=[];count=[];holder={}
    scenes=[('exercise',8,False)]*4+[('ppt',9,False),('exercise',8,False)]+[('blank',10,False)]*3+[('subjective',11,False)]*3+[('subjective',11,True)]
    def html(closed):
        return f'''<script>window.clicked=0</script><div class="slide__cmp"><section class="slide__wrap">
          <img class="cover" src="{uri}" width="400" height="200">
          <div class="time-box"><div class="timing">{'作答已结束' if closed else '倒计时 04:28'}</div></div>
          <p class="options-label MultipleChoice">A</p><p class="options-label MultipleChoice">B</p>
          <div class="submit-btn" onclick="window.clicked++">提交答案</div></section></div>'''
    class Page:
        def __init__(self,real):self.real=real;self.step=0
        @property
        def url(self):
            mode,event,_=scenes[min(self.step,len(scenes)-1)]
            return f'https://www.yuketang.cn/lesson/fullscreen/v3/123/{mode}/{event}'
        def is_closed(self):return False
        def evaluate(self,*a,**kw):return self.real.evaluate(*a,**kw)
        def locator(self,*a,**kw):return self.real.locator(*a,**kw)
        def wait_for_timeout(self,ms):
            self.real.wait_for_timeout(40);self.step+=1
            if self.step>=len(scenes):holder['worker'].stopping.set();return
            self.real.set_content(html(scenes[self.step][2]))
    class Context:
        def __init__(self,page):self.pages=[page]
    class OwnedBrowser:
        def __init__(self,profile,headless=False):self.inner=Browser(profile,headless=True)
        def open(self,url):
            # Production worker requests only the official home page, never an answer API.
            from rainclass.discovery import HOME
            assert url==HOME
            real=self.inner.open('about:blank');real.set_content(html(False))
            self.context=Context(Page(real));return self.context.pages[0]
        def close(self):
            if self.inner.context:count.append(self.inner.page.evaluate('window.clicked'))
            self.inner.close()
    monkeypatch.setattr(real_worker,'Browser',OwnedBrowser)
    def slow_local_ocr(content,layout,kind):
        assert content.startswith(b'\x89PNG');time.sleep(.06)
        assert layout['labels'] and layout['excluded']
        return {'text':'题目文字','stem':'题目文字','options':[], 'kind_hint':'single','source':'test-local','warnings':[],'complete':True}
    monkeypatch.setattr(real_worker,'recognize_question',slow_local_ocr)
    worker=real_worker.RealWorker(tmp_path/'rainclass-edge-profile',tmp_path)
    holder['worker']=worker
    worker.status.connect(observations.append);worker.preview.connect(previews.append)
    worker.notice.connect(notices.append);worker.new_question.connect(messages.append)
    worker.run()
    assert len(worker.monitor.events)==3 and worker.monitor.duplicates_suppressed>=1
    assert count==[0] and len(messages)==3
    assert any(s['state']=='IGNORE_PPT' for s in observations)
    assert any(s['state']=='CLOSED_EXERCISE' for s in observations)
    assert previews and any(not p['ocr_pending'] for p in previews)
    assert observations[-1]['state']=='STOPPED'
    diagnostics=(tmp_path/'real-diagnostics.jsonl').read_text()
    assert '题目文字' not in diagnostics and 'https://' not in diagnostics and 'cookie' not in diagnostics.lower()
    assert not hasattr(worker,'submit') and not hasattr(worker,'analyze')


def test_subjective_late_image_replacement_recaptures_without_duplicate_event(monkeypatch,tmp_path):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage
    from PySide6.QtCore import QBuffer,QIODevice
    from rainclass import real_worker
    app=QApplication.instance() or QApplication([])
    images=[]
    for color in (0xffff0000,0xff0000ff):
        img=QImage(100,80,QImage.Format.Format_RGB32);img.fill(color)
        buffer=QBuffer();buffer.open(QIODevice.OpenModeFlag.WriteOnly);img.save(buffer,'PNG')
        images.append(bytes(buffer.data()))
    uris=['data:image/png;base64,'+base64.b64encode(data).decode() for data in images]
    holder={};previews=[];notifications=[];steps=[0]
    class OwnedBrowser(Browser):
        def __init__(self,profile,headless=False):super().__init__(profile,headless=True)
        def open(self,url):
            super().open('about:blank')
            def handle(route):
                if '/on-lesson' in route.request.url:
                    route.fulfill(status=200,json={'data':{'onLessonClassrooms':[{'lessonId':'123','courseName':'课'}]}})
                elif '/lesson/' in route.request.url:
                    route.fulfill(status=200,content_type='text/html; charset=utf-8',body=f'''
                      <script>history.replaceState({{}},'', '/lesson/fullscreen/v3/123/subjective/7');window.clicked=0</script>
                      <div class="slide__cmp"><div class="slide__wrap"><img class="cover" src="{uris[0]}" width="100" height="80">
                      <div class="time-box"><div class="timing">00:25</div></div>
                      <textarea onclick="window.clicked++"></textarea></div></div>''')
                else:route.fulfill(status=200,body='<p>home</p>')
            self.context.route('https://www.yuketang.cn/**',handle);self.page.goto(url)
            pump=self.page.wait_for_timeout
            def step(ms):
                steps[0]+=1
                live=[p for p in self.context.pages if '/lesson/' in p.url]
                if live and len([p for p in previews if p['ocr_pending']])==1:
                    live[0].locator('img').evaluate('(img,src)=>img.src=src',uris[1])
                if any(not p['ocr_pending'] and p.get('ocr_text')=='latest' for p in previews):
                    assert live[0].evaluate('window.clicked')==0
                    holder['worker'].stopping.set()
                if steps[0]>30:holder['worker'].stopping.set()
                pump(30)
            self.page.wait_for_timeout=step
            return self.page
    def local_ocr(content,*args):
        # The production screenshot can re-encode PNGs; inspect pixels instead.
        pixel=QImage.fromData(content).pixelColor(1,1)
        return {'text':'latest' if pixel.blue()>pixel.red() else 'old','kind_hint':'essay','source':'test'}
    monkeypatch.setattr(real_worker,'Browser',OwnedBrowser)
    monkeypatch.setattr(real_worker,'recognize_question',local_ocr)
    worker=real_worker.RealWorker(tmp_path/'rainclass-edge-profile',tmp_path);holder['worker']=worker
    worker.preview.connect(previews.append);worker.new_question.connect(notifications.append)
    worker.run()
    captures=[p for p in previews if p['ocr_pending']]
    assert len(captures)==2 and len({p['revision'] for p in captures})==2
    assert any(p.get('ocr_text')=='latest' for p in previews)
    assert len(worker.monitor.events)==1 and notifications==['主观题']
    trace=(tmp_path/'real-question-diagnostics.jsonl').read_text()
    assert 'CAPTURE_READY' in trace and 'OCR_READY' in trace
    assert 'data:image' not in trace and 'https://' not in trace and 'latest' not in trace


def test_waiting_without_classroom_preserves_discovery_status(monkeypatch,tmp_path):
    """No classroom page is normal at startup and after class ends."""
    from types import SimpleNamespace
    from PySide6.QtWidgets import QApplication
    from rainclass import real_worker
    app=QApplication.instance() or QApplication([])
    holder={};states=[];notices=[];ticks=[]
    class Home:
        def wait_for_timeout(self,ms):
            if len(ticks)>=3:holder['worker'].stopping.set()
    class OwnedBrowser:
        def __init__(self,*args,**kwargs):self.context=SimpleNamespace(pages=[Home()])
        def open(self,url):pass
        def alive(self):return True
        def close(self):pass
    class Discovery:
        def __init__(self,*args):
            self.phase='discover';self.active=[];self.login_state='SIGNED_IN';self.last_query_at=None;self.last_course='';self.last_entry=None
        def tick(self,*args):ticks.append(1);return 'WAITING_FOR_CLASS'
    monkeypatch.setattr(real_worker,'Browser',OwnedBrowser)
    monkeypatch.setattr(real_worker,'DirectCourseDiscovery',Discovery)
    monkeypatch.setattr(real_worker,'live_page',lambda *args:None)
    w=real_worker.RealWorker(tmp_path/'rainclass-edge-profile',tmp_path);holder['worker']=w
    w.status.connect(states.append);w.notice.connect(notices.append);w.run()
    waiting=[s for s in states if s['state']=='WAITING_FOR_CLASS']
    assert len(waiting)==3 and all(s['lesson_key'] is None for s in waiting)
    assert not any('AttributeError' in s or '读取暂不可用' in s for s in notices)
    assert w.monitor.events==[]
