"""Offline, layout-aware question OCR. Never infers missing answers or option text."""
import importlib
import re
import sys
import threading
import time
from pathlib import Path
from PySide6.QtCore import Qt,QRectF,QBuffer,QIODevice
from PySide6.QtGui import QImage,QPainter,QColor

_engine=None
_lock=threading.Lock()

LAYOUT_SCRIPT='''image => {
 const b=image.getBoundingClientRect();
 const root=image.closest('.slide__wrap');
 const visible=e=>!!e.getClientRects().length && getComputedStyle(e).visibility!=='hidden';
 const box=e=>{const r=e.getBoundingClientRect();return {x:r.x-b.x,y:r.y-b.y,width:r.width,height:r.height}};
 return {width:b.width,height:b.height,
   labels:Array.from(root.querySelectorAll('.options-label')).filter(visible).map(e=>({label:e.innerText.trim(),...box(e)})).filter(e=>/^[A-Z]$/.test(e.label)),
   excluded:Array.from(root.querySelectorAll('.time-box,.submit-btn')).filter(visible).map(box)};
}'''

def _rapid():
    global _engine
    if _engine is not None:return _engine
    vendor=Path(__file__).resolve().parents[2]/'.local/ocr-runtime'
    if not getattr(sys,'frozen',False) and vendor.is_dir() and str(vendor) not in sys.path:sys.path.insert(0,str(vendor))
    module=importlib.import_module('rapidocr')
    models=Path(module.__file__).parent/'models'
    paths={'Det':'PP-OCRv6_det_small.onnx','Rec':'PP-OCRv6_rec_small.onnx','Cls':'ch_ppocr_mobile_v2.0_cls_mobile.onnx'}
    if not all((models/name).is_file() for name in paths.values()):
        raise RuntimeError('Local OCR model files unavailable; no runtime downloads')
    params={'Global.use_cls':False,'Global.log_level':'warning',
        'EngineConfig.onnxruntime.intra_op_num_threads':2,
        'EngineConfig.onnxruntime.inter_op_num_threads':1}
    params.update({key+'.model_path':str(models/name) for key,name in paths.items()})
    _engine=module.RapidOCR(params=params)
    return _engine

def _normal(text):
    return re.sub(r'(?<=[\u4e00-\u9fff])[ \t\u3000]+(?=[\u4e00-\u9fff])','',text).strip()

def _rect(box,sx=1,sy=1):
    return QRectF(float(box['x'])*sx,float(box['y'])*sy,float(box['width'])*sx,float(box['height'])*sy)

def prepare(image_bytes,layout):
    image=QImage.fromData(image_bytes)
    if image.isNull():raise ValueError('Invalid question image')
    width=float(layout.get('width') or image.width());height=float(layout.get('height') or image.height())
    sx=image.width()/width;sy=image.height()/height
    image=image.convertToFormat(QImage.Format.Format_RGB32)
    # Mask the actual DOM overlay bounds, not words guessed from OCR output.
    painter=QPainter(image)
    for box in list(layout.get('excluded',[]))+list(layout.get('labels',[])):
        painter.fillRect(_rect(box,sx,sy).adjusted(-2,-2,2,2),QColor('white'))
    painter.end()
    factor=min(3.0,2000/max(image.width(),image.height()))
    factor=max(1.0,factor)
    target=image.scaled(round(image.width()*factor),round(image.height()*factor),Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation)
    buffer=QBuffer();buffer.open(QIODevice.OpenModeFlag.WriteOnly);target.save(buffer,'PNG')
    return bytes(buffer.data()),target.width()/width,target.height()/height

def _heading(text):
    compact=re.sub(r'\s+','',text)
    return bool(re.fullmatch(r'(?:单选题|多选题|填空题|主观题|简答题)(?:\d+(?:\.\d+)?分)?',compact))

def count_text_blanks(text):
    """Count explicit empty markers across the whole slide, never question numbers."""
    # A numbered platform marker and the underscores on either side are one slot.
    pattern=r'[_＿﹍﹎]*\s*[\[【［]\s*填\s*空\s*\d*\s*[\]】］]\s*[_＿﹍﹎]*|[_＿﹍﹎]{2,}|[（(][ \t\u3000]*[)）]|[【\[][ \t\u3000]*[】\]]'
    count=len(re.findall(pattern,text))
    return count if 1<=count<=50 else None

def ordered_text(items):
    """Group boxes by their actual shared baseline, then read each row left to right."""
    rows=[]
    for block in sorted(items,key=lambda b:(b['y']+b['height']/2,b['x'])):
        center=block['y']+block['height']/2
        row=next((row for row in reversed(rows)
            if abs(center-row[0])<=min(block['height'],row[1])*.5),None)
        if row is None:rows.append([center,block['height'],[block]])
        else:row[2].append(block)
    lines=[]
    for _,_,blocks in rows:
        parts=[_normal(b['text']) for b in sorted(blocks,key=lambda b:b['x'])]
        line=''
        for part in parts:
            if line and re.search(r'[A-Za-z0-9]$',line) and re.match(r'[A-Za-z0-9]',part):line+=' '
            line+=part
        lines.append(line)
    return '\n'.join(lines)

def count_image_blanks(content,blocks):
    """Find separate underline slots which text OCR may omit; require nearby text."""
    import cv2
    import numpy as np
    image=cv2.imdecode(np.frombuffer(content,dtype=np.uint8),cv2.IMREAD_GRAYSCALE)
    height,width=image.shape
    ink=(image<150).astype(np.uint8)
    lines=cv2.morphologyEx(ink,cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT,(max(18,round(width*.025)),1)))
    n,_,stats,_=cv2.connectedComponentsWithStats(lines)
    slots=[]
    for x,y,w,h,area in stats[1:]:
        if y<height*.15 or w>width*.4 or h>max(5,height*.008) or w/h<8:continue
        # Ignore rules, isolated marks and headings without a neighboring statement.
        if not any(w>=b['height']*2 and b['x']+b['width']<=x+5 and x-(b['x']+b['width'])<width*.18
            and b['y']-b['height']*.25<=y<=b['y']+b['height']*1.5
            and re.search(r'[\u4e00-\u9fffA-Za-z]',b['text']) for b in blocks):continue
        slots.append((x,y,w,h))
    return len(slots) if 1<=len(slots)<=50 else None

def split_blocks(blocks,layout,kind='UNKNOWN'):
    """Assign recognized boxes to observed labels. Missing options stay explicitly empty."""
    width=float(layout.get('width',0));height=float(layout.get('height',0))
    anchors=[a for a in layout.get('labels',[]) if re.fullmatch('[A-Z]',a.get('label',''))]
    anchors=sorted(anchors,key=lambda a:a['label'])
    if len({a['label'] for a in anchors})!=len(anchors):
        return {'stem':'','options':[],'complete':False,'warnings':['选项位置重复，请对照原图填写。']}
    option_blocks={a['label']:[] for a in anchors};stem=[];warnings=[]
    exclude=[_rect(b).adjusted(-2,-2,2,2) for b in layout.get('excluded',[])]+[_rect(b).adjusted(-2,-2,2,2) for b in anchors]
    for block in blocks:
        text=_normal(block['text'])
        if not text:continue
        box=_rect(block);center=box.center()
        if any(r.contains(center) for r in exclude):continue
        if (center.x()>width*.9 and center.y()>height*.9 and block.get('score',1)<.8
            and re.fullmatch(r'[.。…eE\s]+',text)):continue
        if center.y()<height*.2 and (_heading(text) or re.fullmatch(r'\d+(?:\.\d+)?\s*分',text)):continue
        candidates=[]
        for anchor in anchors:
            peers=[a for a in anchors if abs(a['x']-anchor['x'])<=max(10,anchor['width'])]
            next_y=min([a['y'] for a in peers if a['y']>anchor['y']+2]+[height])
            next_x=min([a['x'] for a in anchors if a['x']>anchor['x']+anchor['width']*2]+[width])
            left=anchor['x']+anchor['width']
            if left-2<=center.x()<next_x and anchor['y']-anchor['height']*.35<=center.y()<next_y-2:
                candidates.append(anchor)
        if len(candidates)==1:
            option_blocks[candidates[0]['label']].append(block)
        elif not anchors or center.y()<min(a['y'] for a in anchors):stem.append(block)
        else:warnings.append('有文字未能归入题干或选项，请核对原图。')
    stem_text=ordered_text(stem)
    options=[{'label':a['label'],'text':ordered_text(option_blocks[a['label']])} for a in anchors]
    for option in options:
        if not option['text']:warnings.append(option['label']+' 选项未完整识别，请对照原图补充。')
    if not stem_text:warnings.append('题干未完整识别，请对照原图补充。')
    if kind in ('single','multiple') and len(options)<2:warnings.append('选项位置不足，请手动核对。')
    return {'stem':stem_text,'options':options,'complete':not warnings,'warnings':list(dict.fromkeys(warnings))}

def recognize_question(image_bytes,layout=None,kind='UNKNOWN'):
    started=time.monotonic()
    original=QImage.fromData(image_bytes)
    layout={'width':original.width(),'height':original.height(),**(layout or {})}
    content,sx,sy=prepare(image_bytes,layout)
    source='RapidOCR 离线 CPU';warnings=[]
    with _lock:
        try:
            result=_rapid()(content)
            blocks=[]
            if result.boxes is not None:
                for points,text,score in zip(result.boxes,result.txts,result.scores):
                    xs=[float(p[0])/sx for p in points];ys=[float(p[1])/sy for p in points]
                    blocks.append({'text':text,'score':float(score),'x':min(xs),'y':min(ys),'width':max(xs)-min(xs),'height':max(ys)-min(ys)})
        except Exception:
            # No silent low-quality auto-fill when the offline engine is unavailable.
            from .real_review import ocr_bytes
            text=ocr_bytes(content)
            return {'text':text,'stem':'','options':[],'complete':False,'warnings':['离线精确 OCR 不可用，当前为 Windows OCR 原文，请手动核对，未自动填入题干。'],
                    'source':'Windows OCR 回退','requires_review':True,'review_status':'NEEDS_REVIEW','review_reasons':['IMAGE_OCR_UNVERIFIED'],'kind_hint':'UNKNOWN'}
    from .real_review import type_hint
    hint=type_hint('\n'.join(b['text'] for b in blocks))
    result=split_blocks(blocks,layout,kind if kind!='UNKNOWN' else hint)
    if (kind if kind!='UNKNOWN' else hint)=='blank':
        text_count=count_text_blanks(result['stem'])
        # Pixel coordinates refer to the prepared (scaled) image.
        scaled=[{**b,'x':b['x']*sx,'y':b['y']*sy,'width':b['width']*sx,'height':b['height']*sy} for b in blocks]
        image_count=count_image_blanks(content,scaled)
        # Explicit platform labels identify slots even when underline pixels are fragmented.
        labeled=bool(re.search(r'[\[【［]\s*填\s*空\s*\d*\s*[\]】］]',result['stem']))
        conflict=not labeled and text_count and image_count and text_count!=image_count
        result['blank_count']=None if conflict else (text_count or image_count)
        result['warnings'].append('空数识别存在差异，请对照整页核对。' if conflict else
            ('空数为整页空位总数，请核对。' if result['blank_count'] else '未能确定整页空数，请手动核对。'))
        result['complete']=False
    text='\n'.join([result['stem']]+[o['label']+'. '+o['text'] for o in result['options']]).strip()
    return {**result,'text':text,'source':source,'kind_hint':hint,'requires_review':True,
            'review_status':'NEEDS_REVIEW','review_reasons':['IMAGE_OCR_UNVERIFIED'],'ocr_ms':round((time.monotonic()-started)*1000)}
