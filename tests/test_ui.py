def test_ui_lifecycle(monkeypatch, tmp_path):
 monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
 monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
 from PySide6.QtWidgets import QApplication
 from rainclass.app import Window
 app=QApplication.instance() or QApplication([])
 w=Window();assert w.mode.count()==3
 assert w.server.url.startswith('http://127.0.0.1:')
 w.quit()
