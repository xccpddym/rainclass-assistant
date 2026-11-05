import time
from pathlib import Path

def test_short_answer_through_real_worker(monkeypatch,tmp_path):
 monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
 monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
 from PySide6.QtWidgets import QApplication
 from rainclass.app import Window
 app=QApplication.instance() or QApplication([])
 w=Window();w.show()
 def until(predicate,seconds=15):
  end=time.monotonic()+seconds
  while time.monotonic()<end:
   app.processEvents()
   if predicate():return
   time.sleep(.03)
  raise AssertionError(w.status.text()+' / '+w.output.toPlainText())
 try:
  w.server.classroom.update({'action':'start'})
  w.start()
  until(lambda:'普通课件' in w.status.text())
  w.server.classroom.update({'action':'publish','type':'essay','stem':'请简述光合作用的意义。'})
  until(lambda:'【简答题】' in w.output.toPlainText())
  until(lambda:'新题 1' in w.status.text())
  assert '请简述光合作用的意义。' in w.output.toPlainText()
  assert '需人工处理' in w.status.text()
  until(lambda:w.worker.monitor.state=='DUPLICATE')
  assert len(w.worker.monitor.manual_events)==1
  assert w.output.toPlainText().count('【简答题】')==1
  assert '需人工处理' in w.status.text()
  assert w.worker.monitor.api_requests==0
  w.server.classroom.update({'action':'publish','type':'essay','stem':'第二道简答题'})
  until(lambda:'第二道简答题' in w.output.toPlainText())
  until(lambda:'新题 2' in w.status.text())
  report=Path(__file__).resolve().parents[1]/'reports'
  w.grab().save(str(report/'short-answer-desktop.png'))
 finally:
  w.stop()
  until(lambda:not w.worker.isRunning())
  w.quit()

def test_incomplete_essay_is_not_consumed():
 from rainclass.mock import Classroom
 from rainclass.core import Monitor
 c=Classroom();m=Monitor();c.update({'action':'start'})
 c.update({'action':'publish','type':'essay','complete':False})
 assert m.observe(c.snapshot())[0]=='INCOMPLETE'
 assert not m.manual_events
 c.update({'action':'complete'})
 assert m.observe(c.snapshot())[0]=='NEEDS_MANUAL'
 assert len(m.manual_events)==1
