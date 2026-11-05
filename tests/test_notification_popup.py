import json
import os
import subprocess
import sys

def test_popup_visible_on_windows_without_foreground_activation(tmp_path):
    script='''
import ctypes,json
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from rainclass.notification_popup import NewQuestionPopup
app=QApplication([])
before=ctypes.windll.user32.GetForegroundWindow()
popup=NewQuestionPopup()
popup.show_notice('新题提醒测试','发现新题，请核对题目。')
def check():
    print(json.dumps({'visible':popup.isVisible(),'same_foreground':before==ctypes.windll.user32.GetForegroundWindow()}))
    popup.hide();app.quit()
QTimer.singleShot(300,check)
app.exec()
'''
    result=subprocess.run([sys.executable,'-c',script],env={**os.environ,'QT_QPA_PLATFORM':'windows'},capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    state=json.loads(result.stdout.strip().splitlines()[-1])
    assert state=={'visible':True,'same_foreground':True}

def test_popup_switch_test_button_and_main_window_hidden(monkeypatch,tmp_path):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from rainclass.app import Window
    app=QApplication.instance() or QApplication([])
    window=Window(tmp_path)
    try:
        window.hide();window.test_new_question_notification();app.processEvents()
        popup=window.new_question_popup
        assert popup.isVisible() and not window.isVisible()
        assert popup.timer.isActive() and popup.timer.interval()==10000
        rows=[json.loads(line) for line in (tmp_path/'notification-events.jsonl').read_text().splitlines()]
        assert rows[-1]['source']=='test'
        window.new_question_notifications.setChecked(False);app.processEvents()
        assert not popup.isVisible()
        window.on_real_question('单选题');assert not popup.isVisible()
        window.new_question_notifications.setChecked(True)
        window.real_panel.notify.emit('多选题');app.processEvents()
        assert popup.isVisible() and '真实' in popup.title.text()
        popup.timer.timeout.emit();assert not popup.isVisible()
        assert window.real_panel.worker is None
    finally:window.quit()

def test_countdown_and_new_question_popups_have_independent_controls(monkeypatch,tmp_path):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from rainclass.app import Window
    app=QApplication.instance() or QApplication([]);w=Window(tmp_path)
    try:
        w.hide();w.test_new_question_notification();w.test_countdown_notification();app.processEvents()
        assert w.new_question_popup.isVisible() and w.countdown_popup.isVisible()
        assert w.countdown_popup.geometry().bottom()<w.new_question_popup.geometry().top()
        w.countdown_notifications.setChecked(False)
        assert not w.countdown_popup.isVisible() and w.new_question_popup.isVisible()
        w.on_real_alert('剩余20秒');assert not w.countdown_popup.isVisible()
        w.countdown_notifications.setChecked(True);w.new_question_notifications.setChecked(False)
        w.real_panel.time_alert.emit('剩余10秒');app.processEvents()
        assert w.countdown_popup.isVisible() and not w.new_question_popup.isVisible()
        assert '10秒' in w.countdown_popup.message.text()
        w.countdown_popup.timer.timeout.emit();assert not w.countdown_popup.isVisible()
        rows=[json.loads(line) for line in (tmp_path/'notification-events.jsonl').read_text().splitlines()]
        assert rows[-1]['event']=='countdown_popup' and rows[-1]['source']=='real'
        assert w.real_panel.worker is None
    finally:w.quit()


def test_disabled_countdown_test_feedback_visible_on_real_tab(monkeypatch,tmp_path):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from rainclass.app import Window
    app=QApplication.instance() or QApplication([]);w=Window(tmp_path)
    try:
        w.tabs.setCurrentWidget(w.real_panel);w.show();w.countdown_notifications.setChecked(False)
        w.countdown_test.click();app.processEvents()
        assert w.notification_hint.isVisible() and '请先勾选' in w.notification_hint.text()
        assert not w.countdown_popup.isVisible() and not w.countdown_notifications.isChecked()
        w.countdown_notifications.setChecked(True);w.countdown_test.click();app.processEvents()
        assert w.countdown_popup.isVisible() and not w.notification_hint.isVisible()
        assert '10 秒' in w.countdown_popup.message.text()
        assert w.real_panel.worker is None
    finally:w.quit()
