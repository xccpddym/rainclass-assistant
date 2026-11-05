from concurrent.futures import Future
from types import SimpleNamespace
import json

from PySide6.QtWidgets import QApplication, QMessageBox
from rainclass.real_panel import RealPanel
from rainclass.storage import Store


def dispose(app,*panels):
    for p in panels:
        p.ai_timer.stop();p.analysis=None;p.deleteLater()
    app.processEvents()


def test_restart_restores_exact_strategy_and_connection(tmp_path):
    app=QApplication.instance() or QApplication([])
    p=RealPanel(tmp_path,tmp_path/'rainclass-edge-profile')
    p.run_mode.setCurrentIndex(1);p.essay_mode.setCurrentIndex(1)
    for name in ('follow_new','auto_answer','essay_auto_submit','ai_persist','fit_image'):
        getattr(p,name).setChecked(False)
    p.ai_enabled.setChecked(True)
    p.auto_enter.setChecked(False);p.silent_recovery.setChecked(True)
    p.refresh_limit.setValue(4);p.preferred.setText('测试课堂')
    p.profile.setText(str(tmp_path/'another'/'rainclass-edge-profile'))
    other=RealPanel(tmp_path,tmp_path/'default'/'rainclass-edge-profile')
    try:
        assert other.run_mode.currentData()=='auto' and other.essay_mode.currentData()=='auto'
        assert other.ai_enabled.isChecked()
        assert all(not getattr(other,n).isChecked() for n in ('follow_new','auto_answer','essay_auto_submit','ai_persist','fit_image','auto_enter'))
        assert other.silent_recovery.isChecked() and other.refresh_limit.value()==4
        assert other.preferred.text()=='测试课堂' and other.profile.text()==p.profile.text()
        assert other.worker is None and other.analysis is None and other.answer_valid is None
    finally:dispose(app,p,other)


def test_unlimited_switch_preserves_amount_and_survives_restart(tmp_path):
    app=QApplication.instance() or QApplication([])
    p=RealPanel(tmp_path,tmp_path/'rainclass-edge-profile')
    p.budget_info.setValue(.8);p.budget_enabled.setChecked(False)
    other=RealPanel(tmp_path,tmp_path/'rainclass-edge-profile');other.update_config_summary()
    try:
        assert other.ai_config['budget'] is None and not other.budget_info.isEnabled()
        assert other.ai_config['call_limit'] is None
        assert other.budget_info.value()==.8
        other.budget_enabled.setChecked(True)
        assert other.ai_config['budget']==.8 and other.budget_info.isEnabled()
    finally:dispose(app,p,other)


def test_clear_offline_usage_and_history_with_confirmation(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    p=RealPanel(tmp_path,tmp_path/'rainclass-edge-profile')
    store=Store(tmp_path/'analysis.sqlite3')
    q=SimpleNamespace(course_id='lesson',instance_id='one')
    store.record(q,'model','OK',{},1,{'max_request_cost':.1})
    store.save('key',q,{'answer':'A'});store.close()
    attempts=tmp_path/'real-submit-attempts.json';attempts.write_text('{"one":"CONFIRMED"}')
    try:
        monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.StandardButton.No)
        p.clear_analysis_history()
        store=Store(tmp_path/'analysis.sqlite3');assert store.summary();store.close()
        monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.StandardButton.Yes)
        p.clear_analysis_history()
        store=Store(tmp_path/'analysis.sqlite3')
        assert store.summary()==[] and store.history()==[] and store.cached('key') is None
        assert store.allowance('lesson',1,.1,.1)
        store.close()
        assert json.loads(attempts.read_text())=={'one':'CONFIRMED'}
    finally:dispose(app,p)


def test_cannot_clear_during_request(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    p=RealPanel(tmp_path,tmp_path/'rainclass-edge-profile')
    p.analysis=SimpleNamespace(closing=False,requests={'one':Future()})
    monkeypatch.setattr(QMessageBox,'question',lambda *a:(_ for _ in ()).throw(AssertionError('must not ask')))
    try:
        p.clear_analysis_history()
        assert '请等待分析完成' in p.ai_output.toPlainText()
    finally:dispose(app,p)
