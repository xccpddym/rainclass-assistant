import time
import pytest
from rainclass.mock import Classroom,Server
from rainclass.timing import TimingPolicy
from rainclass.browser import Browser,MockAdapter

def make():
 c=Classroom();c.update({'action':'start'});c.update({'action':'publish','id':'one','seconds':15});return c

def test_timing_resync_unknown_and_close():
 c=make();p=TimingPolicy();remaining,alerts=p.observe(c.snapshot())
 assert 13<remaining<=15 and alerts==[30,20]
 assert p.observe(c.snapshot())[1]==[]
 c.update({'action':'extend','seconds':8});assert p.observe(c.snapshot())[1]==[10]
 c.update({'action':'extend','seconds':120});assert p.observe(c.snapshot())[0]>118
 c.update({'action':'online','value':False});assert p.observe(c.snapshot())[0] is None
 c.update({'action':'online','value':True});c.update({'action':'close'});assert p.observe(c.snapshot())[0] is None

@pytest.mark.parametrize('mode,remaining,reviewed,expected',[('review',5,False,False),('review',5,True,True),('auto',50,False,True),('smart',11,False,False),('smart',9,False,True),('auto',None,False,False),('auto',0,False,False)])
def test_modes(mode,remaining,reviewed,expected):
 p=TimingPolicy();p.instance='one';p.mode=mode
 assert p.should_submit({'question_instance_id':'one'},remaining,reviewed)==expected
 assert not p.should_submit({'question_instance_id':'old'},remaining,True)

def test_server_receipt_idempotence_and_expiry():
 c=make();receipt=c.submit({'instance_id':'one','answers':['B']});assert receipt['environment']=='MOCK_ONLY'
 with pytest.raises(ValueError):c.submit({'instance_id':'one','answers':['B']})
 c.update({'action':'publish','seconds':-1})
 with pytest.raises(ValueError):c.submit({'instance_id':c.snapshot()['question']['id'],'answers':['B']})

def test_origin_guard():
 class Page:url='https://www.yuketang.cn/v2/web/index'
 with pytest.raises(ValueError,match='origin'):MockAdapter('http://127.0.0.1:1234').submit(Page(),{})

@pytest.mark.parametrize('kind,answers',[('single',['B']),('multiple',['A','B']),('blank',['4','6'])])
def test_edge_fill_and_submit(tmp_path,kind,answers):
 srv=Server().start();browser=Browser(tmp_path/'rainclass-edge-profile')
 try:
  srv.classroom.update({'action':'start'});srv.classroom.update({'action':'publish','type':kind,'id':'one'})
  page=browser.open(srv.url+'/student');page.wait_for_function('window.classroomState?.question?.id === "one"')
  receipt=MockAdapter(srv.url).submit(page,dict(question_instance_id='one',suggested_answer=answers,explanation='本地测试',uncertainty='仅演示'))
  assert receipt['answers']==answers and len(srv.classroom.receipts)==1
  assert page.locator('#receipt').inner_text().find('模拟提交成功')>=0
 finally:browser.close();srv.close()

@pytest.mark.parametrize('mode,seconds,manual',[('auto',60,False),('smart',9,False),('review',60,True)])
def test_desktop_submission(monkeypatch,tmp_path,mode,seconds,manual):
 monkeypatch.setenv('QT_QPA_PLATFORM','offscreen');monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
 from PySide6.QtWidgets import QApplication
 from rainclass.app import Window
 app=QApplication.instance() or QApplication([]);w=Window()
 def until(predicate):
  end=time.monotonic()+15
  while time.monotonic()<end:
   app.processEvents()
   if predicate():return
   time.sleep(.03)
  raise AssertionError(w.output.toPlainText())
 try:
  w.mode.setCurrentIndex({'review':0,'smart':1,'auto':2}[mode]);w.start()
  w.server.classroom.update({'action':'start'});w.server.classroom.update({'action':'publish','seconds':seconds})
  if manual:
   until(lambda:'分析结果：' in w.output.toPlainText());assert not w.server.classroom.receipts;w.review_submit()
  until(lambda:len(w.server.classroom.receipts)==1)
  assert not w.cloud.isChecked()
  assert w.server.classroom.receipts[0]['environment']=='MOCK_ONLY'
 finally:
  w.stop();until(lambda:not w.worker.isRunning());w.quit()


def test_stale_snapshot_and_custom_threshold():
 c=make();s=c.snapshot();s['observed_at']=time.time()-10
 p=TimingPolicy(threshold=5);p.mode='smart'
 assert p.observe(s)[0] is None
 s=c.snapshot();p.observe(s)
 assert not p.should_submit({'question_instance_id':'one'},7)
 assert p.should_submit({'question_instance_id':'one'},4)
 s['question']['deadline']=float('nan');assert p.observe(s)[0] is None

@pytest.mark.parametrize('change',[{'action':'online','value':False},{'action':'end'},{'action':'close'}])
def test_submit_rejects_unavailable(change):
 c=make();c.update(change)
 with pytest.raises(ValueError):c.submit({'instance_id':'one','answers':['B']})


def test_no_repeat_reminder_after_disconnect():
 c=make();p=TimingPolicy();assert p.observe(c.snapshot())[1]
 p.observe({'online':False})
 assert p.observe(c.snapshot())[1]==[]
