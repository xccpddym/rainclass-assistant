import time,json

def test_notification_controls_with_edge(monkeypatch,tmp_path):
 monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
 from PySide6.QtWidgets import QApplication
 from rainclass.app import Window
 app=QApplication.instance() or QApplication([])
 w=Window(data_dir=tmp_path);messages=[]
 monkeypatch.setattr(w.tray,'showMessage',lambda *args:messages.append(args))
 monkeypatch.setattr(w.new_question_popup,'show_notice',lambda *args:messages.append(args))
 monkeypatch.setattr(w.countdown_popup,'show_notice',lambda *args:messages.append(args))
 def until(predicate):
  end=time.monotonic()+15
  while time.monotonic()<end:
   app.processEvents()
   if predicate():return
   time.sleep(.03)
  raise AssertionError(w.output.toPlainText())
 try:
  assert w.new_question_notifications.isChecked()
  w.countdown_notifications.setChecked(False)
  w.start();w.server.classroom.update({'action':'start'})
  w.server.classroom.update({'action':'publish','type':'single','id':'one'})
  until(lambda:'one' in w.worker.results)
  assert len(messages)==1 and '单选题' in messages[0][1]
  w.show_history();w.force_analysis()
  until(lambda:len(w.worker.futures)==0)
  assert len(messages)==1
  w.new_question_notifications.setChecked(False)
  w.server.classroom.update({'action':'publish','type':'blank','id':'two'})
  until(lambda:'two' in w.worker.results)
  assert len(messages)==1
  w.on_alert('十秒提醒');assert len(messages)==1
  w.countdown_notifications.setChecked(True);w.on_alert('十秒提醒')
  assert len(messages)==2
  w.new_question_notifications.setChecked(True)
  w.server.classroom.update({'action':'publish','type':'essay','id':'three'})
  until(lambda:len(w.worker.monitor.manual_events)==1)
  until(lambda:len(messages)==3)
  assert '简答题' in messages[-1][1]
  w.new_question_notifications.setChecked(False);w.countdown_notifications.setChecked(False)
 finally:
  w.stop();until(lambda:not w.worker.isRunning());w.quit()
 saved=json.loads((tmp_path/'ui-preferences.json').read_text())
 assert saved=={'new_question_notifications':False,'countdown_notifications':False,'essay_sound':True}
 w2=Window(data_dir=tmp_path)
 try:
  assert not w2.new_question_notifications.isChecked() and not w2.countdown_notifications.isChecked()
 finally:w2.quit()


def test_essay_sound_independent_of_popups_and_persisted(monkeypatch,tmp_path):
 from PySide6.QtWidgets import QApplication
 from rainclass.app import Window
 app=QApplication.instance() or QApplication([])
 w=Window(data_dir=tmp_path);sounds=[]
 monkeypatch.setattr(w,'play_essay_sound',lambda:sounds.append('sound'))
 try:
  assert w.essay_sound.isChecked()
  assert w.real_panel.settings_page.isAncestorOf(w.essay_sound)
  assert w.real_panel.settings_page.isAncestorOf(w.essay_sound_test)
  w.new_question_notifications.setChecked(False)
  w.on_real_question('主观题');assert sounds==['sound']
  for kind in ('填空题','互动题','单选题','多选题'):w.on_real_question(kind)
  assert sounds==['sound']
  w.essay_sound.setChecked(False);w.on_real_question('主观题')
  assert sounds==['sound']
 finally:w.quit()
 w2=Window(data_dir=tmp_path)
 try:assert not w2.essay_sound.isChecked()
 finally:w2.quit()


def test_essay_sound_uses_system_audio_and_test_button(monkeypatch,tmp_path):
 import sys
 from types import SimpleNamespace
 from PySide6.QtWidgets import QApplication
 from rainclass.app import Window
 app=QApplication.instance() or QApplication([]);sounds=[]
 monkeypatch.setitem(sys.modules,'winsound',SimpleNamespace(MB_ICONEXCLAMATION=48,MessageBeep=lambda value:sounds.append(value)))
 w=Window(data_dir=tmp_path)
 try:
  w.essay_sound_test.click();assert sounds==[48]
  def fail(value):raise RuntimeError('no system sound')
  monkeypatch.setitem(sys.modules,'winsound',SimpleNamespace(MB_ICONEXCLAMATION=48,MessageBeep=fail))
  monkeypatch.setattr(QApplication,'beep',lambda:sounds.append('fallback'))
  w.play_essay_sound();assert sounds==[48,'fallback']
 finally:w.quit()
