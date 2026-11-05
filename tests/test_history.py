import pytest
from rainclass.browser import Browser
from rainclass.history import HistoryExtractor
from rainclass.core import Monitor

@pytest.fixture(scope='module')
def edge(tmp_path_factory):
 b=Browser(tmp_path_factory.mktemp('history')/'rainclass-edge-profile');page=b.open('about:blank')
 yield page
 b.close()
class Frame:
 url='https://www.yuketang.cn/m/v2/lesson/student/test/overview'
 def __init__(self,page):self.page=page
 def evaluate(self,script):return self.page.evaluate(script)
 def locator(self,selector):return self.page.locator(selector)
class Report:
 url='https://www.yuketang.cn/v2/web/student-lesson-report/test/course/user'
 def __init__(self,page):self.frames=[Frame(page)]

HTML='<div class="courseware-cmp-wrap"><section class="slides-list">\n<div class="slide-item"><aside class="slide-stats"><div class="text"><span>P1</span></div></aside>普通PPT中的选择题文字A/B/C/D</div>\n<div class="slide-item active-slide-item"><aside class="slide-stats"><div class="text"><span>P2</span></div></aside><div class="slide-img"><img width="20" height="20" src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a6y4AAAAASUVORK5CYII="></div><section class="slide-exercise"><span>未作答</span></section></div>\n<div class="slide-item" style="display:none"><section class="slide-exercise">隐藏副本</section></div>\n</section></div>'

def test_history_is_separate_and_deduplicable(edge):
 edge.set_content(HTML);p=Report(edge);a=HistoryExtractor();one=a.extract(p);two=a.extract(p)
 assert one['historical'] and not one['ai_allowed'] and one['question'] is None
 assert one['visible_slides']==2 and len(one['questions'])==1
 assert one['questions'][0]['page_label']=='P2'
 assert one['questions'][0]['exercise_status']=='UNANSWERED'
 assert one['questions'][0]['question_type']=='UNKNOWN'
 assert one['questions'][0]['instance_key']==two['questions'][0]['instance_key']
 m=Monitor();m.observe(one);assert not m.events and m.api_requests==0
 assert 'data:image' not in str(one)

def test_plain_slides_are_not_exercises(edge):
 edge.set_content('<div class="courseware-cmp-wrap"><section class="slides-list"><div class="slide-item">单选题 A B C D 提交 倒计时</div></section></div>')
 assert not HistoryExtractor().extract(Report(edge))['questions']

def test_wrong_route_or_frame_rejected(edge):
 p=Report(edge);p.url='https://www.yuketang.cn/v2/web/index'
 with pytest.raises(ValueError):HistoryExtractor().extract(p)
 p=Report(edge);p.frames[0].url='https://www.yuketang.cn.example.com/m/v2/lesson/student/test/overview'
 with pytest.raises(ValueError):HistoryExtractor().extract(p)

def test_selected_requires_formal_exercise(edge):
 edge.set_content('<p>普通课件</p>')
 with pytest.raises(ValueError):HistoryExtractor().selected(Report(edge))

def test_local_windows_ocr(monkeypatch,tmp_path):
 monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
 from PySide6.QtWidgets import QApplication
 from PySide6.QtGui import QImage,QPainter,QFont,QColor,QFontDatabase
 from rainclass.ocr import recognize
 app=QApplication.instance() or QApplication([])
 image=QImage(1000,140,QImage.Format.Format_RGB32);image.fill(0xffffffff)
 font_id=QFontDatabase.addApplicationFont(r'C:\Windows\Fonts\arial.ttf')
 assert font_id>=0
 family=QFontDatabase.applicationFontFamilies(font_id)[0]
 painter=QPainter(image);painter.setPen(QColor('black'));painter.setFont(QFont(family,48));painter.drawText(30,95,'RAINCLASS 2468');painter.end()
 path=tmp_path/'本地 OCR 测试.png';assert image.save(str(path))
 result=recognize(path)
 assert '2468' in result['text'] and result['requires_review'] and result['source']=='Windows local OCR'
 assert '公式' in result['warning']
