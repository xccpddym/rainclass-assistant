import time

def test_desktop_fake_result(monkeypatch,tmp_path):
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
  raise AssertionError(w.output.toPlainText()+' / '+w.status.text())
 try:
  assert not w.cloud.isChecked()
  w.server.classroom.update({'action':'start'});w.server.classroom.update({'action':'publish'})
  w.start();until(lambda:'分析结果：' in w.output.toPlainText())
  assert '本地演示模型' in w.output.toPlainText()
  w.show_history();assert '本地演示，非真实解答' in w.output.toPlainText()
  assert '本次生成' in w.output.toPlainText()
 finally:
  w.stop();until(lambda:not w.worker.isRunning());w.quit()
