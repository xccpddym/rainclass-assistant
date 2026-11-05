def test_review_status_remains_explicit_until_human_confirmation(monkeypatch,tmp_path):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from rainclass.real_panel import RealPanel
    app=QApplication.instance() or QApplication([])
    panel=RealPanel(tmp_path,tmp_path/'rainclass-edge-profile')
    try:
        panel.on_state({'state':'ACTIVE_EXERCISE','instance_key':'one'})
        base={'instance_key':'one','revision':'r1','image':b'','question_type':'essay','ocr_pending':True}
        panel.on_preview(base)
        panel.on_preview({**base,'ocr_pending':False,'ocr_text':'x²','candidate':{'stem':'x²','options':[],'review_status':'NEEDS_REVIEW'}})
        assert panel.review_status=='NEEDS_REVIEW' and 'NEEDS_REVIEW' in panel.review_label.text()
        panel.confirm();assert panel.review_status=='REVIEWED'
        panel.stem.setPlainText('x³');assert panel.review_status=='NEEDS_REVIEW' and panel.confirmed is None
        panel.invalidate();assert panel.review_status=='NEEDS_REVIEW'
    finally:panel.deleteLater();app.processEvents()

def test_signed_in_class_found_with_auto_entry_off_is_visible(monkeypatch,tmp_path):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from rainclass.real_panel import RealPanel
    app=QApplication.instance() or QApplication([]);panel=RealPanel(tmp_path,tmp_path/'rainclass-edge-profile')
    try:
        panel.on_state({'state':'AUTO_ENTER_DISABLED','login_state':'SIGNED_IN','active_count':1,'last_query_at':1700000000})
        text=panel.state_label.text()
        assert '已登录' in text and '正在上课 1 门' in text and '自动进入已关闭' in text and '最近查询' in text
        assert not panel.confirm_button.isEnabled()
    finally:panel.deleteLater();app.processEvents()
