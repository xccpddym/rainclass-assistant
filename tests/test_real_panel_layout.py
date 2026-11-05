"""UI-only regression checks; no user browser or real model requests."""
from threading import Event
import pytest
from PySide6.QtCore import QObject,Signal,QBuffer,QIODevice
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication,QPushButton
from rainclass.real_panel import RealPanel


@pytest.fixture
def panel(tmp_path):
    app=QApplication.instance() or QApplication([])
    from rainclass.ui_fonts import configure_fonts
    configure_fonts(app)
    p=RealPanel(tmp_path,tmp_path/'rainclass-edge-profile')
    p.resize(1280,820);p.show();app.processEvents()
    yield p
    p.stop();p.settings_page.hide();p.settings_page.setParent(p);p.hide();p.deleteLater();app.processEvents()


def feed(p):
    image=QImage(960,540,QImage.Format.Format_RGB32);image.fill(0xffffffff)
    buffer=QBuffer();buffer.open(QIODevice.OpenModeFlag.WriteOnly);image.save(buffer,'PNG')
    p.on_state({'state':'ACTIVE_EXERCISE','instance_key':'one','remaining_seconds':60})
    payload={'instance_key':'one','revision':'r1','image':bytes(buffer.data()),'question_type':'blank','ocr_pending':True}
    p.on_preview(payload)
    p.on_preview({**payload,'ocr_pending':False,'ocr_text':'测试原文','candidate':{'stem':'题干____','options':[],'blank_count':1}})
    QApplication.processEvents()


def test_tabs_and_settings_preserve_question_and_hidden_updates(panel):
    feed(panel);panel.confirm();draft=panel.confirmed;payload=panel.payload
    panel.log.insertPlainText('已收到新题\n')
    for index in (1,0,1,0):
        panel.review_tabs.setCurrentIndex(index)
        panel.settings_button.click();QApplication.processEvents()
    assert panel.confirmed is draft and panel.payload is payload
    assert panel.stem.toPlainText()=='题干____' and panel.blanks.value()==1
    assert panel.ocr.toPlainText()=='测试原文' and '已收到新题' in panel.log.toPlainText()
    assert panel.worker is None
    panel.hide();panel.on_state({'state':'ACTIVE_EXERCISE','instance_key':'one','remaining_seconds':42})
    assert '00:42' in panel.timer_label.text()


def test_expanded_settings_scroll_in_small_window(panel):
    feed(panel)
    panel.resize(1000,650);panel.settings_page.setParent(None);panel.settings_page.resize(1000,650);panel.settings_page.show();QApplication.processEvents()
    assert panel.settings_panel.isVisible() and panel.height()==650
    assert panel.settings_area.verticalScrollBar().maximum()>0


def test_splitters_resize_image_without_changing_original(panel):
    feed(panel);original=panel.original_image.cacheKey()
    for size in ((1280,820),(1000,650),(1366,768)):
        panel.resize(*size);QApplication.processEvents()
        panel.question_splitter.setSizes([320,size[0]-320]);panel.content_splitter.setSizes([380,200])
        QApplication.processEvents();panel.question_splitter.splitterMoved.emit(320,1)
        panel.content_splitter.splitterMoved.emit(380,1);QApplication.processEvents()
        pixmap=panel.image.pixmap();view=panel.image_area.viewport()
        assert not pixmap.isNull() and pixmap.width()<=view.width() and pixmap.height()<=view.height()
        assert abs(pixmap.width()/pixmap.height()-960/540)<.02
        assert panel.original_image.cacheKey()==original
        assert panel.width()==size[0] and panel.height()==size[1]
    panel.fit_image.setChecked(False);assert panel.image.pixmap().size()==panel.original_image.size()
    panel.fit_image.setChecked(True);assert panel.image.minimumWidth()==0
    panel.content_splitter.setSizes([300,300]);QApplication.processEvents()
    assert panel.log.height()>150


def test_settings_roundtrip_and_clear_log_preserve_database(panel):
    from rainclass.storage import Store
    path=panel.data_dir/'analysis.sqlite3';s=Store(path)
    with s.db:s.db.execute("INSERT INTO history(created,course,instance,result) VALUES (1,'c','i','{}')")
    s.close();before=path.read_bytes()
    panel.log.setPlainText('日志');panel.clear_log_button.click()
    assert panel.log.toPlainText()=='' and path.read_bytes()==before
    panel.auto_enter.setChecked(False);panel.silent_recovery.setChecked(True)
    panel.preferred.setText('测试课程');panel.preferred.editingFinished.emit()
    panel.refresh_limit.setValue(4)
    other=RealPanel(panel.data_dir,panel.profile.text())
    try:
        assert not other.auto_enter.isChecked() and other.silent_recovery.isChecked()
        assert other.preferred.text()=='测试课程'
        assert other.refresh_limit.value()==4
    finally:other.deleteLater()


def test_refresh_limit_default_and_immediate_worker_update(panel):
    assert panel.refresh_limit.value()==2
    from rainclass.real_worker import RealWorker
    panel.worker=RealWorker(panel.profile.text(),panel.data_dir)
    panel.refresh_limit.setValue(0);assert panel.worker.refresh_limit==0
    panel.refresh_limit.setValue(5);assert panel.worker.refresh_limit==5


class StubWorker(QObject):
    answer_status=Signal(str)
    status=Signal(dict);preview=Signal(dict);notice=Signal(str)
    new_question=Signal(str);alert=Signal(str);finished=Signal()
    def __init__(self,*args):
        super().__init__();self.starts=0;self.running=False
        for field in ('stopping','paused','capture_request','recover_request','follow_enabled','silent_recovery','auto_enter'):
            setattr(self,field,Event())
    def start(self):self.starts+=1;self.running=True
    def isRunning(self):return self.running


def test_all_controls_keep_worker_and_signal_connections(panel,monkeypatch):
    from rainclass import real_panel
    created=[]
    def factory(*args):
        worker=StubWorker();created.append(worker);return worker
    monkeypatch.setattr(real_panel,'RealWorker',factory)
    messages=[];alerts=[];panel.notify.connect(messages.append);panel.time_alert.connect(alerts.append)
    panel.start_button.click();worker=panel.worker;panel.start_button.click()
    assert len(created)==1 and worker.starts==1
    for _ in range(3):
        panel.review_tabs.setCurrentIndex(1);panel.settings_button.click();panel.review_tabs.setCurrentIndex(0)
    assert panel.worker is worker and worker.starts==1 and not worker.stopping.is_set()
    worker.status.emit({'state':'ACTIVE_EXERCISE','instance_key':'one','remaining_seconds':30})
    worker.notice.emit('后台日志');worker.new_question.emit('填空题');worker.alert.emit('剩余30秒')
    assert '后台日志' in panel.log.toPlainText() and messages==['填空题'] and alerts==['剩余30秒']
    panel.pause_button.click();assert worker.paused.is_set()
    panel.pause_button.click();assert not worker.paused.is_set()
    panel.recover_button.click();assert worker.recover_request.is_set()
    panel.refresh_button.click();assert worker.capture_request.is_set()
    panel.follow_new.setChecked(False);assert not worker.follow_enabled.is_set()
    feed(panel)
    panel.stem.clear();panel.options.clear()
    copy=next(b for b in panel.findChildren(QPushButton) if b.text().startswith('填入识别'))
    copy.click();assert panel.stem.toPlainText()=='题干____'
    panel.confirm_button.click();assert panel.review_status=='REVIEWED'
    panel.stop_button.click();assert worker.stopping.is_set() and panel.confirmed is None
    worker.running=False;worker.finished.emit();assert panel.profile.isEnabled()

def test_window_settings_tab_reuses_worker_draft_and_controls(tmp_path):
    from rainclass.app import Window
    app=QApplication.instance() or QApplication([])
    w=Window(tmp_path);w.show();app.processEvents();p=w.real_panel
    worker=StubWorker();worker.running=True;p.worker=worker
    worker.status.connect(p.on_state);worker.notice.connect(p.log.insertPlainText)
    try:
        assert [w.tabs.tabText(i) for i in range(w.tabs.count())]==['真实课堂','课堂设置','本地模拟']
        feed(p);p.confirm();draft=p.confirmed;payload=p.payload
        controls=(p.run_mode,p.essay_mode,p.ai_enabled,p.profile,p.refresh_limit,w.new_question_notifications)
        for _ in range(3):
            p.settings_button.click();app.processEvents()
            assert w.tabs.currentWidget() is p.settings_page and p.settings_area.isVisible()
            worker.status.emit({'state':'ACTIVE_EXERCISE','instance_key':'one','remaining_seconds':22})
            worker.notice.emit('设置页期间仍接收日志')
            p.settings_back.click();app.processEvents()
            assert w.tabs.currentWidget() is p
        assert p.worker is worker and worker.starts==0 and p.confirmed is draft and p.payload is payload
        assert '00:22' in p.timer_label.text() and '仍接收日志' in p.log.toPlainText()
        assert controls==(p.run_mode,p.essay_mode,p.ai_enabled,p.profile,p.refresh_limit,w.new_question_notifications)
        assert p.analysis is None
        assert p.settings_page.isAncestorOf(w.new_question_notifications)
        assert p.settings_page.isAncestorOf(p.run_mode)
        assert not p.isAncestorOf(p.run_mode)
    finally:
        worker.running=False;w.quit();w.hide();w.deleteLater();app.processEvents()


def test_budget_setting_range_persists_and_updates_service(tmp_path):
    from types import SimpleNamespace
    app=QApplication.instance() or QApplication([])
    p=RealPanel(tmp_path,tmp_path/'rainclass-edge-profile')
    other=None
    try:
        assert p.budget_info.minimum()==.1 and p.budget_info.maximum()==10 and p.budget_info.value()==.5
        p.ai_config={'budget':1,'profiles':[]};p.update_config_summary();assert p.ai_config['budget']==.5
        p.analysis=SimpleNamespace(closing=False,service=SimpleNamespace(budget=.5))
        p.analysis.set_budget=lambda value: (setattr(p.analysis.service,'budget',value) or [])
        p.budget_info.setValue(.7)
        assert p.analysis.service.budget==.7 and p.ai_config['budget']==.7
        other=RealPanel(tmp_path,tmp_path/'rainclass-edge-profile')
        assert other.budget_info.value()==.7
        p.budget_info.setValue(.5)
        assert p.analysis.service.budget==.5
    finally:
        p.analysis=None;p.ai_timer.stop();p.deleteLater()
        if other:other.ai_timer.stop();other.deleteLater()
        app.processEvents()
