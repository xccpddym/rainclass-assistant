"""Read the signed-in site's on-lesson status without navigating course cards."""
import hashlib
import re
import time
from urllib.parse import urlsplit
from .discovery import CourseDiscovery,HOME
from .live import page_identity

QUERY=r'''async () => {
 const abort=new AbortController();const timer=setTimeout(()=>abort.abort(),5000);
 try {
   const response=await fetch('/api/v3/classroom/on-lesson',
     {method:'GET',credentials:'same-origin',signal:abort.signal,redirect:'error'});
   if(response.status===401||response.status===403)return {state:'LOGIN_REQUIRED'};
   if(!response.ok)return {state:'NOT_VERIFIED'};
   const data=await response.json();const rows=data?.data?.onLessonClassrooms;
   if(!Array.isArray(rows))return {state:'NOT_VERIFIED'};
   return {state:'OK',lessons:rows.map(row=>({id:String(row.lessonId??row.lesson_id??''),
     course:typeof row.courseName==='string'?row.courseName:''}))};
 } catch(e) {return {state:'NOT_VERIFIED'};} finally {clearTimeout(timer);}
}'''

class DirectCourseDiscovery(CourseDiscovery):
    def __init__(self,notice,ended,stopping,**kwargs):
        super().__init__(notice,**kwargs)
        self.ended=ended;self.stopping=stopping;self.phase='query';self.probe=None
        self.entry_page=None;self.entry_tries={}
        self.login_state='NOT_VERIFIED';self.last_query_at=None
        self.live_next_at=0;self.live_lesson=None;self.live_missing=0

    def check_current(self,page,force=False):
        """True: currently listed; False: absent twice; None: not yet confirmed.

        Use the already open official classroom, without navigation or new tabs.
        An expired login or failed query is never evidence that class ended.
        """
        lesson=page_identity(page.url)[0]
        if lesson!=self.live_lesson:
            self.live_lesson=lesson;self.live_missing=0;self.live_next_at=0
        if not force and self.clock()<self.live_next_at:return None
        self.live_next_at=self.clock()+10
        try:data=page.evaluate(QUERY)
        except Exception:
            self.live_missing=0;self.login_state='NOT_VERIFIED';return None
        self.last_query_at=time.time()
        if not isinstance(data,dict) or data.get('state')!='OK':
            self.live_missing=0
            self.login_state='LOGIN_REQUIRED' if isinstance(data,dict) and data.get('state')=='LOGIN_REQUIRED' else 'NOT_VERIFIED'
            if self.login_state=='LOGIN_REQUIRED':self.say('登录已失效，请在 Edge 中正常扫码登录。')
            return None
        rows=data.get('lessons')
        if not isinstance(rows,list) or any(not isinstance(r,dict) or not isinstance(r.get('id'),str) or not re.fullmatch(r'[0-9]{1,30}',r['id']) for r in rows):
            self.live_missing=0;self.login_state='NOT_VERIFIED';return None
        self.login_state='SIGNED_IN'
        self.active=[{'lesson':r['id'],'course':r.get('course','')} for r in rows
                     if hashlib.sha256(r['id'].encode()).hexdigest() not in self.ended]
        if any(r['id']==lesson for r in rows):
            self.live_missing=0;return True
        self.live_missing+=1
        return False if self.live_missing>=2 else None

    def tick(self,context,enabled,preferred=''):
        if self.stopping.is_set():return 'STOPPED'
        if self.clock()<self.next_at:return self.wait_state
        self.phase='query'
        if self.probe is None or self.probe.is_closed():
            pages=[p for p in context.pages if not p.is_closed() and p.url==HOME]
            self.probe=pages[0] if pages else context.new_page()
            if self.probe.url!=HOME:self.probe.goto(HOME,wait_until='domcontentloaded')
        u=urlsplit(self.probe.url)
        if u.scheme!='https' or u.hostname!='www.yuketang.cn' or u.port not in (None,443) or u.username or u.password:
            self.next_at=self.clock()+10;return 'LOGIN_REQUIRED'
        data=self.probe.evaluate(QUERY)
        self.last_query_at=time.time()
        self.next_at=self.clock()+10
        if data.get('state')!='OK':
            self.login_state='LOGIN_REQUIRED' if data.get('state')=='LOGIN_REQUIRED' else 'NOT_VERIFIED'
            self.wait_state=data.get('state','NOT_VERIFIED')
            if self.wait_state=='LOGIN_REQUIRED':self.say('登录已失效，请在 Edge 中正常扫码登录。')
            else:self.say('正在上课状态暂不可用，稍后重试；不会逐门打开课程。')
            return self.wait_state
        self.login_state='SIGNED_IN'
        lessons={}
        for row in data.get('lessons',[]):
            if not isinstance(row,dict):continue
            identity=row.get('id','')
            if not isinstance(identity,str) or not re.fullmatch(r'[0-9]{1,30}',identity):continue
            if hashlib.sha256(identity.encode()).hexdigest() in self.ended:continue
            lessons[identity]={'lesson':identity,'course':row.get('course','')}
        self.active=list(lessons.values());self.names=[c['course'] for c in self.active]
        selected=[c for c in self.active if c['course']==preferred] if preferred else self.active
        if preferred and not selected:selected=self.active
        if not enabled:self.wait_state='AUTO_ENTER_DISABLED' if self.active else 'WAITING_FOR_CLASS'
        elif len(selected)>1:
            self.wait_state='COURSE_CHOICE_REQUIRED';self.say('多门课堂正在进行，请设置唯一优先课程或手动选择。')
        elif not selected:self.wait_state='WAITING_FOR_CLASS'
        else:
            if self.stopping.is_set():return 'STOPPED'
            self.target=selected[0];self.phase='enter';self.enter_at=self.clock()
            lesson=self.target['lesson']
            if self.entry_tries.get(lesson,0)>=3:
                self.wait_state='NOT_VERIFIED';self.say('课堂页面未能完成进入，已停止重复打开；可点击恢复课堂重试。');return self.wait_state
            self.entry_tries[lesson]=self.entry_tries.get(lesson,0)+1
            if self.entry_page is None or self.entry_page.is_closed():self.entry_page=context.new_page()
            page=self.entry_page
            page.goto('https://www.yuketang.cn/lesson/fullscreen/v3/'+self.target['lesson'],wait_until='domcontentloaded')
            return self._enter(context)
        return self.wait_state

    def _enter(self,context):
        for page in context.pages:
            if page.is_closed():continue
            try:lesson,_,_=page_identity(page.url)
            except ValueError:continue
            if lesson==self.target['lesson']:
                self.last_course=self.target['course'];self.phase='live'
                self.say('已直接进入正在进行的课堂。');return 'ENTERING_CLASS'
        self.wait_state='NOT_VERIFIED';self.say('课堂入口尚未完成加载，将重新检查上课状态。')
        return self.wait_state
