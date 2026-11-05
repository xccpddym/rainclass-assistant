"""Offline packaged OCR verification; no classroom, user profile, or model API."""
import json,sys
from pathlib import Path
from PySide6.QtGui import QImage,QPainter,QFont
from PySide6.QtCore import QBuffer,QIODevice
from .question_ocr import recognize_question
from .ui_fonts import configure_fonts

def run(app,report):
    configure_fonts(app)
    image=QImage(700,180,QImage.Format.Format_RGB32);image.fill(0xffffffff)
    painter=QPainter(image);painter.setFont(QFont('Microsoft YaHei',26))
    painter.drawText(30,100,'离线 OCR 测试 12345');painter.end()
    buffer=QBuffer();buffer.open(QIODevice.OpenModeFlag.WriteOnly);image.save(buffer,'PNG')
    import requests
    requests.sessions.Session.request=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('Network forbidden'))
    result=recognize_question(bytes(buffer.data()),kind='essay')
    data={'pass':result['source']=='RapidOCR 离线 CPU' and '12345' in result['text'] and result['review_status']=='NEEDS_REVIEW',
        'frozen':bool(getattr(sys,'frozen',False)),'source':result['source'],'review_status':result['review_status'],'cloud_requests':0}
    Path(report).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if data['pass'] else 1
