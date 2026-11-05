"""Read-only extraction for observed historical lesson report iframe, never live."""
import re,hashlib,tempfile
from pathlib import Path
from urllib.parse import urlsplit
class HistoryExtractor:
 def frame(self,page):
  top=urlsplit(page.url)
  if top.scheme!='https' or top.hostname!='www.yuketang.cn' or top.port not in (None,443) or not top.path.startswith('/v2/web/student-lesson-report/'):
   raise ValueError('Allowed historical lesson report required')
  frames=[f for f in page.frames if urlsplit(f.url).scheme=='https' and urlsplit(f.url).hostname=='www.yuketang.cn' and urlsplit(f.url).port in (None,443) and re.fullmatch(r'/m/v2/lesson/student/[^/]+/overview',urlsplit(f.url).path)]
  if len(frames)!=1:raise ValueError('Historical overview frame unavailable or ambiguous')
  return frames[0]
 def extract(self,page):
  frame=self.frame(page)
  data=frame.evaluate("""()=>{
   const visible=e=>!!(e&&e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden');
   const text=e=>visible(e)?e.innerText.trim():'';
   const items=Array.from(document.querySelectorAll('.courseware-cmp-wrap .slides-list .slide-item')).filter(visible);
   const questions=items.map((e,index)=>({index,page_label:text(e.querySelector('.slide-stats .text span')),exercise_status:text(e.querySelector('.slide-exercise')),exercise:visible(e.querySelector('.slide-exercise')),selected:e.classList.contains('active-slide-item'),image_count:Array.from(e.querySelectorAll('.slide-img img')).filter(visible).length})).filter(e=>e.exercise);
   return {visible_slides:items.length,questions};
  }""")
  scope=hashlib.sha256(urlsplit(frame.url).path.encode()).hexdigest()
  for q in data['questions']:
   status=q['exercise_status']
   q['exercise_status']='UNANSWERED' if '未作答' in status else 'ANSWERED' if '提交答案' in status else 'UNKNOWN'
   q.update(historical=True,question_type='UNKNOWN',content_status='NEEDS_IMAGE_REVIEW',instance_key=scope+':'+str(q['index']),ai_allowed=False)
  return {'page_state':'HISTORICAL_LESSON_REVIEW','historical':True,'question':None,'ai_allowed':False,**data}
 def selected(self,page,ocr=False):
  data=self.extract(page);selected=[q for q in data['questions'] if q['selected']]
  if len(selected)!=1:raise ValueError('Select one formal historical exercise first')
  frame=self.frame(page);image=frame.locator('.center-big-slide-wrap .one-page-slide img.slide-img:visible')
  if image.count()!=1:raise ValueError('Historical question image unavailable')
  result={**selected[0],'requires_review':True}
  with tempfile.TemporaryDirectory(prefix='rainclass-history-') as temporary:
   path=Path(temporary)/'question.png';image.screenshot(path=str(path))
   result['image_digest']=hashlib.sha256(path.read_bytes()).hexdigest()
   if ocr:
    from .ocr import recognize
    result['ocr']=recognize(path);result['content_status']='OCR_NEEDS_REVIEW'
  return result
