import json
import time
from threading import Event
import pytest
from rainclass.real_review import validate_draft,load_seen,save_seen,type_hint

def test_review_validation_and_irrelevant_fields():
    q=validate_draft('one','image-1','single','2+2=?','A. 3\nB. 4',9)
    assert q.options==('3','4') and q.blank_count==0
    q=validate_draft('two','image-2','essay','解释原因','旧选项',2)
    assert q.options==() and q.blank_count==0
    with pytest.raises(ValueError):validate_draft('one','image','UNKNOWN','题干','',1)
    with pytest.raises(ValueError):validate_draft('one','image','blank','题干','',0)
    with pytest.raises(ValueError):validate_draft('one','image','single','题干','A.',1)

def test_only_hashes_are_restored_and_dedup_survives_restart(tmp_path):
    from rainclass.live import LiveReadOnlyMonitor
    key='a'*64;path=tmp_path/'seen.json'
    save_seen(path,{key})
    m=LiveReadOnlyMonitor();m.seen=load_seen(path)
    s={'state':'ACTIVE_EXERCISE','observed_at':1,'exercise':{'instance_key':key,'question_type':'blank'}}
    assert m.observe(s) is None and len(m.events)==0
    path.write_text(json.dumps([key,'cookie','https://example.com','b'*64]),encoding='utf-8')
    assert load_seen(path)=={key,'b'*64}
    path.write_text('{broken',encoding='utf-8');assert load_seen(path)==set()

def test_ocr_kind_is_only_a_hint():
    assert type_hint('多 选 题\n以下哪些是偶数')=='multiple'
    assert type_hint('单选题 多选题')=='UNKNOWN'
    assert type_hint('2+2=?')=='UNKNOWN'

def test_silent_recovery_setting_defaults_off_and_persists(panel):
    from rainclass.real_worker import RealWorker
    from rainclass.real_panel import RealPanel
    assert not panel.silent_recovery.isChecked()
    panel.worker=RealWorker(panel.profile.text(),panel.data_dir)
    panel.silent_recovery.setChecked(True)
    assert panel.worker.silent_recovery.is_set()
    restored=RealPanel(panel.data_dir,panel.profile.text())
    try:assert restored.silent_recovery.isChecked()
    finally:restored.deleteLater()
    panel.silent_recovery.setChecked(False)
    assert not panel.worker.silent_recovery.is_set()
    assert json.loads((panel.data_dir/'lifecycle-settings.json').read_text())['silent_recovery'] is False

@pytest.fixture
def panel(monkeypatch,tmp_path):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from rainclass.real_panel import RealPanel
    app=QApplication.instance() or QApplication([])
    p=RealPanel(tmp_path,tmp_path/'rainclass-edge-profile')
    yield p
    p.stop();p.deleteLater();app.processEvents()

def active(panel,key='one'):
    panel.on_state({'state':'ACTIVE_EXERCISE','instance_key':key,'remaining_seconds':60,'events':1})


def test_clear_log_preserves_monitoring_and_files(panel):
    marker=panel.data_dir/'real-seen.json';marker.write_text('["seen"]')
    active(panel);panel.log.insertPlainText('切题提示\n')
    panel.clear_log_button.click()
    assert panel.log.toPlainText()==''
    assert panel.active_key=='one' and marker.read_text()=='["seen"]'
    panel.log.insertPlainText('后续日志\n')
    assert '后续日志' in panel.log.toPlainText()

def preview(key='one',rev='r1',pending=True):
    return {'instance_key':key,'revision':rev,'image':b'','question_type':'UNKNOWN','ocr_text':'单选题\n2+2=?','ocr_pending':pending,'type_hint':'single'}

def fill(panel):
    panel.kind.setCurrentIndex(panel.kind.findData('single'))
    panel.stem.setPlainText('2+2=?');panel.options.setPlainText('3\n4')

def test_manual_confirmation_no_analysis_and_expiry(panel):
    active(panel);panel.on_preview(preview());fill(panel);panel.confirm()
    assert panel.confirmed and panel.confirmed.options==('3','4')
    panel.stem.setPlainText('3+3=?');assert panel.confirmed is None
    panel.last_active_at=time.monotonic()-4;panel.confirm()
    assert panel.confirmed is None and '未及时同步' in panel.review_label.text()
    active(panel,'two');assert not panel.confirm_button.isEnabled()
    panel.confirm();assert panel.confirmed is None

def test_delayed_ocr_never_replaces_new_question_or_manual_edit(panel):
    active(panel);panel.on_preview(preview());fill(panel)
    panel.on_preview(preview(pending=False))
    assert panel.stem.toPlainText()=='2+2=?'
    active(panel,'two');panel.on_preview(preview('two','r2'));panel.stem.setPlainText('新题')
    panel.on_preview(preview(pending=False))
    assert panel.payload['instance_key']=='two' and panel.stem.toPlainText()=='新题'
    panel.on_preview(preview('two','r3'));panel.stem.setPlainText('第三次读取')
    panel.on_preview(preview('two','r2',False))
    assert panel.payload['revision']=='r3' and panel.stem.toPlainText()=='第三次读取'

def test_structured_ocr_fills_separate_fields_without_controls(panel):
    active(panel);panel.on_preview(preview())
    result={'stem':'以下哪些属于计算机输入设备？','options':[{'label':a,'text':t} for a,t in zip('ABCD',['键盘','鼠标','显示器','麦克风'])], 'source':'离线 OCR','warnings':[]}
    panel.on_preview({**preview(pending=False),'candidate':result,'type_hint':'multiple'})
    assert panel.stem.toPlainText()=='以下哪些属于计算机输入设备？'
    assert panel.options.toPlainText()=='A. 键盘\nB. 鼠标\nC. 显示器\nD. 麦克风'
    panel.stem.setPlainText('人工改过的题干')
    panel.on_preview({**preview(pending=False),'candidate':result})
    assert panel.stem.toPlainText()=='人工改过的题干'

def test_whole_slide_blank_count_prefill_and_manual_edit_protection(panel):
    active(panel)
    pending={**preview(),'question_type':'blank'}
    panel.on_preview(pending)
    assert panel.blanks.value()==0 and panel.blanks.text()=='待核对'
    candidate={'stem':'1. CPU 是____。\n2. RAM 是____。','options':[], 'blank_count':2}
    ready={**pending,'ocr_pending':False,'candidate':candidate}
    panel.on_preview(ready)
    assert panel.blanks.value()==2
    panel.confirm()
    assert panel.confirmed.blank_count==2
    panel.blanks.setValue(3)
    panel.on_preview(ready)
    assert panel.blanks.value()==3
    active(panel,'two')
    panel.on_preview({**pending,'instance_key':'two','revision':'r2'})
    assert panel.blanks.value()==0
    panel.stem.setPlainText('看不清空位的题干');panel.confirm()
    assert panel.confirmed is None and '填空数量' in panel.review_label.text()

@pytest.mark.parametrize('state',['IGNORE_PPT','CLOSED_EXERCISE','RECOVERING','FOLLOWING_EXERCISE','PAUSED','STOPPED'])
def test_nonactive_state_invalidates_draft(panel,state):
    active(panel);panel.on_preview(preview());fill(panel);panel.confirm()
    panel.on_state({'state':state,'instance_key':None})
    assert panel.confirmed is None and not panel.confirm_button.isEnabled()

def test_notification_settings_apply_to_real_classroom(monkeypatch,tmp_path):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from rainclass.app import Window
    app=QApplication.instance() or QApplication([])
    w=Window(tmp_path);messages=[]
    monkeypatch.setattr(w.tray,'showMessage',lambda *args:messages.append(args))
    monkeypatch.setattr(w.new_question_popup,'show_notice',lambda *args:messages.append(args))
    monkeypatch.setattr(w.countdown_popup,'show_notice',lambda *args:messages.append(args))
    try:
        assert w.tabs.count()==3
        w.real_panel.notify.emit('单选题');assert len(messages)==1 and '真实' in messages[0][0]
        w.new_question_notifications.setChecked(False)
        w.real_panel.notify.emit('多选题');assert len(messages)==1
        w.countdown_notifications.setChecked(False);w.real_panel.time_alert.emit('倒计时');assert len(messages)==1
        assert not hasattr(w.real_panel,'submit') and not hasattr(w.real_panel,'analyze')
    finally:w.quit()
