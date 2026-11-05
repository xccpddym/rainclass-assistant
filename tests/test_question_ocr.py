import importlib.util
from pathlib import Path
import pytest
from rainclass.question_ocr import split_blocks,recognize_question

@pytest.mark.parametrize('text,expected',[
    ('1. CPU 是____。\n2. RAM 是____。',2),
    ('1. 分别为（ ）和（　）。',2),
    ('1. 填写＿＿＿。\n2. 填写【 】。',2),
    ('1. 第一题\n2. 第二题',None),
    ('x = (a+b) - 1',None),
    ('只有一个____。',1),
    ('一个字节通常由_[填空1]_个二进制位组成。\n十进制数10的二进制表示为_[填空2]。',2),
    ('先填＿［填 空 1］＿，再填__[填空2]__。',2),
    ('_[填空1]_，另有____。',2),
])
def test_count_all_slide_blank_markers(text,expected):
    from rainclass.question_ocr import count_text_blanks
    assert count_text_blanks(text)==expected

def test_underlines_omitted_by_ocr_are_counted_from_image():
    import cv2
    import numpy as np
    from rainclass.question_ocr import count_image_blanks
    image=np.full((400,600),255,dtype=np.uint8)
    cv2.line(image,(210,150),(310,150),0,2)
    cv2.line(image,(210,250),(310,250),0,2)
    # A page rule and an isolated minus sign must not add blanks.
    cv2.line(image,(20,80),(580,80),0,2)
    cv2.line(image,(450,350),(480,350),0,2)
    content=cv2.imencode('.png',image)[1].tobytes()
    blocks=[block('1. CPU 是',40,125,160,24),block('2. RAM 是',40,225,160,24)]
    assert count_image_blanks(content,blocks)==2

def layout():
    return {'width':475,'height':373,
        'labels':[{'label':letter,'x':84,'y':y,'width':30,'height':31} for letter,y in zip('ABCD',[154,201,247,294])],
        'excluded':[{'x':350,'y':0,'width':125,'height':35},{'x':350,'y':335,'width':125,'height':38}]}

def block(text,x,y,w=60,h=16):return {'text':text,'x':x,'y':y,'width':w,'height':h,'score':.99}

def test_layout_separates_options_and_excludes_even_garbled_controls():
    blocks=[block('多选题1分',10,3),block('题干含 0 与 A，不应丢掉',60,80,250),
        block('0',90,160,12),block('键盘',140,160),block('鼠标',140,207),block('显示器',140,253),block('麦克风',140,300),
        block('辅计时14：',360,4),block('提歧答萦',360,343)]
    result=split_blocks(blocks,layout(),'multiple')
    assert result['stem']=='题干含 0 与 A，不应丢掉'
    assert [o['text'] for o in result['options']]==['键盘','鼠标','显示器','麦克风']
    assert result['complete'] is True

def test_missing_options_stay_empty_not_guessed():
    result=split_blocks([block('题干',60,80),block('键盘',140,160)],layout(),'multiple')
    assert result['options'][1]=={'label':'B','text':''}
    assert not result['complete'] and any('B 选项' in x for x in result['warnings'])

def test_multiline_options_and_legitimate_zero_survive():
    result=split_blocks([block('题干',60,80),block('第一行',140,160),block('第二行',140,180),block('0',140,207),block('-1',140,253),block('A + B',140,300)],layout(),'single')
    assert result['options'][0]['text']=='第一行\n第二行'
    assert result['options'][1]['text']=='0'

def test_fragmented_blank_rows_keep_reading_order_despite_different_heights():
    # The old y/box-height sort put the small label ahead of the first statement.
    blocks=[block('[填空1]',175,82,50,10),block('一个字节通常由_',20,80,150,16),
        block('_个二进制位组成。',230,79,150,18),
        block('十进制数10的二进制表示为_[填空2]。',20,120,370,30)]
    result=split_blocks(blocks,{'width':500,'height':300},'blank')
    assert result['stem']=='一个字节通常由_[填空1]_个二进制位组成。\n十进制数10的二进制表示为_[填空2]。'

def test_user_two_blank_screenshot_offline(monkeypatch):
    import requests
    monkeypatch.setattr(requests.sessions.Session,'request',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('Network forbidden during OCR')))
    areas={'width':501,'height':283,'excluded':[
        {'x':400,'y':0,'width':101,'height':24},
        {'x':360,'y':249,'width':110,'height':33}]}
    result=recognize_question((Path(__file__).parent/'fixtures/two_blanks_controls.png').read_bytes(),areas,'blank')
    assert result['source']=='RapidOCR 离线 CPU'
    assert result['blank_count']==2
    assert result['stem']=='一个字节通常由_[填空1]_个二进制位组成。\n十进制数10的二进制表示为_[填空2]。'
    assert not result['options'] and result['requires_review']

@pytest.mark.parametrize('with_controls',[False,True])
def test_user_screenshot_chinese_options_offline(monkeypatch,with_controls):
    root=Path(__file__).resolve().parents[1]
    if not (root/'.local/ocr-runtime/rapidocr').is_dir() and importlib.util.find_spec('rapidocr') is None:
        pytest.skip('Install optional offline OCR for the real-image regression')
    import requests
    monkeypatch.setattr(requests.sessions.Session,'request',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('Network forbidden during OCR')))
    filename='input_devices_controls.png' if with_controls else 'input_devices.png'
    content=(Path(__file__).parent/'fixtures'/filename).read_bytes()
    areas=layout()
    if with_controls:
        areas={'width':504,'height':284,'labels':[{'label':letter,'x':65,'y':y,'width':24,'height':23} for letter,y in zip('ABCD',[118,152,188,222])],
               'excluded':[{'x':401,'y':3,'width':102,'height':22},{'x':365,'y':252,'width':70,'height':29}]}
    result=recognize_question(content,areas,'multiple')
    assert result['source']=='RapidOCR 离线 CPU'
    assert result['stem']=='以下哪些属于计算机输入设备？'
    assert [o['text'] for o in result['options']]==['键盘','鼠标','显示器','麦克风']
    assert result['complete'] and result['requires_review']
    assert result['text']=='以下哪些属于计算机输入设备？\nA. 键盘\nB. 鼠标\nC. 显示器\nD. 麦克风'

def test_windows_fallback_does_not_fill_raw_noise(monkeypatch):
    import rainclass.question_ocr as module
    import rainclass.real_review as review
    monkeypatch.setattr(module,'_rapid',lambda:(_ for _ in ()).throw(ImportError()))
    monkeypatch.setattr(review,'ocr_bytes',lambda image:'多选题\n0\n辅计时 14:')
    content=(Path(__file__).parent/'fixtures/input_devices.png').read_bytes()
    result=recognize_question(content,layout(),'multiple')
    assert result['stem']=='' and not result['options'] and not result['complete']
