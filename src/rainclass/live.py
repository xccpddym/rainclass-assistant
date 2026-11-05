"""Read-only v3 classroom evidence. Image exercises never become AI-ready questions."""
import hashlib
import re
import time
from urllib.parse import urlsplit

STRUCTURE_SCRIPT = r'''() => {
 const visible=e=>!!(e&&e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden');
 const all=(root,s)=>Array.from(root.querySelectorAll(s)).filter(visible);
 const wraps=all(document,'.slide__cmp .slide__wrap');
 return {wraps:wraps.map(e=>({
   images:all(e,'img.cover').length,
   timing:all(e,'.time-box .timing').map(n=>n.innerText.trim()),
   submit:all(e,'.submit-btn').filter(n=>['提交答案','作答'].includes(n.innerText.trim())).length,
   option_labels:all(e,'.options-label').map(n=>n.innerText.trim()).filter(t=>/^[A-Z]$/.test(t)),
   text_fields:all(e,'input:not([type=hidden]):not([type=password]),textarea,[contenteditable=true]').length
 })),timeline_exercises:all(document,'.timeline__ppt.problem').length,
 current_ppt_markers:all(document,'.inlesson').length,
 visible_elements:all(document,'body *').length};
}'''

def page_identity(url):
    u=urlsplit(url)
    if u.scheme!='https' or u.hostname!='www.yuketang.cn' or u.port not in (None,443) or u.username or u.password:
        raise ValueError('Exact official HTTPS classroom required')
    match=re.fullmatch(r'/lesson/fullscreen/v3/([0-9]+)/(ppt|exercise|blank|subjective)/([0-9]+)',u.path)
    if not match:
        shell=re.fullmatch(r'/lesson/fullscreen/v3/([0-9]+)/?',u.path)
        if shell:return shell.group(1),'pending','0'
        raise ValueError('Observed v3 classroom route required')
    return match.groups()

def interpret(url, data):
    lesson, mode, event=page_identity(url)
    result={'page_state':'LIVE_CLASSROOM_V3','state':'IGNORE_PPT' if mode=='ppt' else 'NOT_VERIFIED',
        'question':None,'ai_allowed':False,'submit_allowed':False,'historical':False,
        'observed_at':time.time(),'exercise':None,
        'structure':{'visible_elements':data.get('visible_elements',0),
                     'timeline_exercises':data.get('timeline_exercises',0),
                     'route_mode':mode,'route_key':hashlib.sha256(f'{lesson}/{mode}/{event}'.encode()).hexdigest()}}
    def waiting(reason):
        result['structure']['verification_reason']=reason
        return result
    if mode in ('ppt','pending'):return waiting('PPT' if mode=='ppt' else 'ROUTE_PENDING')
    wraps=data.get('wraps',[])
    result['structure']['wrap_count']=len(wraps)
    if len(wraps)!=1:return waiting('CONTAINER_COUNT')
    w=wraps[0]
    result['structure'].update(image_count=w.get('images',0),submit_count=w.get('submit',0),
                               timing_count=len(w.get('timing',[])),text_field_count=w.get('text_fields',0))
    if w.get('images')!=1:return waiting('IMAGE_COUNT')
    # A subjective editor can mount before its submit control. It is sufficient
    # for read-only capture only with the same container's image and valid timer.
    editor_ready=mode=='subjective' and w.get('submit')==0 and w.get('text_fields',0)>0
    if w.get('submit')!=1 and not editor_ready:return waiting('ANSWER_UI')
    if len(w.get('timing',[]))!=1:return waiting('TIMING_COUNT')
    timing=re.sub(r'\s+','',w['timing'][0]).replace('：',':')
    closed='作答已结束' in timing
    match=re.fullmatch(r'(?:倒计时\s*)?(\d{1,3}):(\d{2})(?::(\d{2}))?',timing)
    seconds=None
    if match:
        a,b,c=match.groups()
        if int(b)<60 and (c is None or int(c)<60):
            seconds=int(a)*60+int(b) if c is None else int(a)*3600+int(b)*60+int(c)
    state='CLOSED_EXERCISE' if closed or seconds==0 else 'ACTIVE_EXERCISE' if seconds is not None else 'NOT_VERIFIED'
    result.update(state=state,historical=closed)
    result['structure']['verification_reason']='VERIFIED' if state!='NOT_VERIFIED' else 'TIMER_FORMAT'
    result['exercise']={'instance_key':hashlib.sha256(f'{lesson}/{mode}/{event}'.encode()).hexdigest(),
        'formal_ui':True,'closed':closed or seconds==0,'remaining_seconds':seconds,
        'option_count':len(w.get('option_labels',[])),
        'question_type':{'blank':'blank','subjective':'essay'}.get(mode,'UNKNOWN'),
        'content_status':'IMAGE_REQUIRES_REVIEW','requires_review':True}
    return result

class LiveReadOnlyAdapter:
    def snapshot(self,page):
        page_identity(page.url)
        return interpret(page.url,page.evaluate(STRUCTURE_SCRIPT))

    async def snapshot_async(self,page):
        page_identity(page.url)
        return interpret(page.url,await page.evaluate(STRUCTURE_SCRIPT))

class LiveReadOnlyMonitor:
    def __init__(self):
        self.seen=set()
        self.events=[]
        self.duplicates_suppressed=0

    def observe(self,snapshot):
        if snapshot['state']!='ACTIVE_EXERCISE':return None
        q=snapshot['exercise']
        key=q['instance_key']
        if key in self.seen:
            self.duplicates_suppressed+=1
            return None
        self.seen.add(key)
        event={'instance_key':key,'detected_at':snapshot['observed_at'],
               'question_type':q['question_type'],'requires_review':True}
        self.events.append(event)
        return event
