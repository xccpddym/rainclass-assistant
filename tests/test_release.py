import sys

def test_frozen_config_uses_exe_directory(monkeypatch,tmp_path):
 monkeypatch.setenv('QT_QPA_PLATFORM','offscreen');monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'data'))
 from PySide6.QtWidgets import QApplication
 from rainclass.app import Window
 app=QApplication.instance() or QApplication([])
 folder=tmp_path/'portable';folder.mkdir();(folder/'config.toml').write_text('[browser]\nhealth_interval=1.25\n',encoding='utf-8')
 monkeypatch.setattr(sys,'frozen',True,raising=False);monkeypatch.setattr(sys,'executable',str(folder/'App.exe'))
 monkeypatch.chdir(tmp_path)
 w=Window()
 try:assert w.config['browser']['health_interval']==1.25
 finally:w.quit()
