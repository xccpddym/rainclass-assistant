"""Explicitly register installed Windows fonts for Qt Chinese rendering."""
import os
from pathlib import Path
from PySide6.QtGui import QFont,QFontDatabase

_configured=False
def configure_fonts(app):
    global _configured
    if _configured or os.name!='nt' or app is None:return
    fonts=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'Fonts'
    for name in ('arial.ttf','msyh.ttc','msyhbd.ttc'):
        path=fonts/name
        if path.is_file():QFontDatabase.addApplicationFont(str(path))
    if 'Microsoft YaHei' in QFontDatabase.families():app.setFont(QFont('Microsoft YaHei',10))
    _configured=True
