"""Packaged-app acceptance: only local mock, FakeAI, no user credentials."""
import time,json,sys
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from .storage import Store
class SmokeRun:
 def __init__(self,w,path):
  self.w=w;self.path=Path(path).resolve();self.started=time.monotonic();self.stage=0
  self.results=[];self.errors=[];self.finishing=False;self.failed=False
  w.worker=None;w.cloud.setChecked(False);w.headless.setChecked(True);w.config['ai']={}
  self.timer=QTimer();self.timer.timeout.connect(self.tick)
 def start(self):
  self.w.server.classroom.update({'action':'start'});self.w.start()
  self.w.worker.question.connect(self.message);self.timer.start(100)
 def message(self,text):
  if text.startswith('分析结果：'):self.results.append(text)
  if '失败' in text or '未确认' in text:self.errors.append(text)
 def publish(self,kind,ident):self.w.server.classroom.update({'action':'publish','type':kind,'id':ident})
 def tick(self):
  if self.finishing:return
  if time.monotonic()-self.started>60:self.finish(True);return
  m=self.w.worker.monitor
  if self.stage==0 and m.state=='IGNORE_PPT':
   for _ in range(50):self.w.server.classroom.update({'action':'ppt'})
   self.ppt_at=time.monotonic();self.stage=1
  elif self.stage==1 and time.monotonic()-self.ppt_at>1:
   if m.events or m.manual_events:self.finish(True);return
   self.publish('single','smoke-one');self.stage=2
  elif self.stage==2 and len(self.results)==1:self.publish('multiple','smoke-two');self.stage=3
  elif self.stage==3 and len(self.results)==2:self.publish('blank','smoke-three');self.stage=4
  elif self.stage==4 and len(self.results)==3:self.publish('essay','smoke-four');self.stage=5
  elif self.stage==5 and len(m.manual_events)==1:
   self.w.mode.setCurrentIndex(2);self.publish('single','smoke-five');self.stage=6
  elif self.stage==6 and len(self.w.server.classroom.receipts)==1 and len(self.results)==4:self.finish(False)
 def finish(self,failed):
  self.failed=failed;self.finishing=True;self.timer.stop();self.w.stop();self.wait_exit()
 def wait_exit(self):
  if self.w.worker.isRunning():QTimer.singleShot(100,self.wait_exit);return
  store=Store(self.w.data/'analysis.sqlite3');usage=store.summary();history=store.history();store.close()
  receipt=self.w.server.classroom.receipts
  passed=not self.failed and not self.errors and len(self.results)==4 and len(receipt)==1 and not usage and len(self.w.worker.monitor.events)==4 and len(self.w.worker.monitor.manual_events)==1
  data={'pass':passed,'frozen':bool(getattr(sys,'frozen',False)),'seconds':time.monotonic()-self.started,'stage':self.stage,'supported_questions':len(self.w.worker.monitor.events),'manual_questions':len(self.w.worker.monitor.manual_events),'fake_results':len(self.results),'cache_hit_observed':any('复用历史缓存' in text for text in self.results),'cloud_requests':sum(row['requests'] for row in usage),'mock_receipts':len(receipt),'history_records':len(history),'error_count':len(self.errors),'browser':'Microsoft Edge headless','real_platform':'NOT_VERIFIED','dual_device':'NOT_RUN_USER_DEFERRED'}
  self.path.parent.mkdir(parents=True,exist_ok=True)
  self.w.grab().save(str(self.path.with_suffix('.png')))
  self.path.write_text(json.dumps(data,indent=2),encoding='utf-8')
  self.w.server.close();self.w.tray.hide();QApplication.instance().exit(0 if passed else 1)
