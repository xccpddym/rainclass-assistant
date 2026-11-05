"""Discover active classes using only the observed student course list and logs UI."""
import time
import re
import hashlib
from urllib.parse import urlsplit

HOME='https://www.yuketang.cn/v2/web/index'

def valid_entry(entry):
    if not isinstance(entry,dict) or not isinstance(entry.get('course'),str):return None
    try:
        u=urlsplit(entry['url'])
        if u.scheme=='https' and u.hostname=='www.yuketang.cn' and u.port in (None,443) and not(u.username or u.password) and u.path.startswith('/v2/web/studentLog/'):
            return {'course':entry['course'],'url':entry['url']}
    except (ValueError,TypeError,KeyError):pass
    return None

class CourseDiscovery:
    def __init__(self,notice,clock=time.monotonic,resume=None,blocked=None):
        self.notice=notice;self.clock=clock;self.page=None;self.index=0;self.names=[]
        self.active=[];self.next_at=0;self.phase='home';self.last_notice=None
        self.last_course=''
        self.ready_since=None;self.entering=False;self.enter_at=0
        self.resume=valid_entry(resume);self.last_entry=None
        self.resume_hint=self.resume;self.enter_attempts=0;self.enter_retry_at=0
        self.preferred_probed=False
        self.blocked=blocked if blocked is not None else set()
        self.wait_state='WAITING_FOR_CLASS'

    def mark_ended(self):
        target=getattr(self,'target',{})
        if target.get('record_key'):self.blocked.add(target['record_key'])
        self.resume=self.resume_hint=self.last_entry=None
        self.last_course='';self.active=[];self.index=0;self.page=None;self.phase='home'
        self.next_at=self.clock()+30;self.wait_state='WAITING_FOR_CLASS'
        self.say('课堂已结束，已停止旧课堂恢复，继续等待下一节课。')

    def home(self):
        # Use the site's own SPA history rather than reloading authentication/home each time.
        self.page.go_back(wait_until='domcontentloaded')
        if self.page.url!=HOME:self.page.goto(HOME,wait_until='domcontentloaded')

    def say(self,message):
        if message!=self.last_notice:self.notice(message);self.last_notice=message

    def tick(self,context,enabled,preferred=''):
        if self.clock()<self.next_at:return self.wait_state
        if self.page is None or self.page.is_closed():
            resume=self.resume if enabled and self.resume and (not preferred or preferred==self.resume['course']) else None
            destination=resume['url'] if resume else HOME
            candidates=[p for p in context.pages if not p.is_closed() and p.url==destination]
            self.page=candidates[0] if candidates else context.new_page()
            if self.page.url!=destination:self.page.goto(destination,wait_until='domcontentloaded')
            self.phase='resume' if resume else 'home';self.index=0;self.active=[];self.ready_since=None
            if resume:self.names=[resume['course']]
            self.resume=None
        p=self.page
        u=urlsplit(p.url)
        if u.scheme!='https' or u.hostname!='www.yuketang.cn' or u.port not in (None,443) or u.username or u.password:
            self.say('登录状态需要确认，请正常扫码登录后继续。');return 'LOGIN_REQUIRED'
        # Authentication can briefly redirect to the login/home route, then restore
        # the original detail URL. Reconcile the state with that actual route.
        if self.phase=='home' and self.resume_hint and p.url==self.resume_hint['url']:
            self.phase='resume';self.names=[self.resume_hint['course']];self.index=0;self.active=[];self.ready_since=None
        if self.phase=='home':
            signed=p.locator('.index__view .el-tabs__item.is-active').all_text_contents()
            if not any('我听的课' in t for t in signed):
                body=p.locator('body').inner_text(timeout=1500)
                if re.search(r'(?:微信|请|使用).*扫码|扫码登录|登录已过期|登录失效',body):
                    self.say('登录已失效或尚未登录，请停止监测后重新启动，在 Edge 中正常扫码。')
                    return 'LOGIN_REQUIRED'
                return 'NOT_VERIFIED'
            self.names=p.locator('.index__view .el-card.box-card h1:visible').all_text_contents()
            if not self.names:
                if self.ready_since is None:self.ready_since=self.clock()
                if self.clock()-self.ready_since<3:return 'DISCOVERING'
            else:self.ready_since=None
            desired=preferred or (self.resume_hint['course'] if self.resume_hint else '')
            matches=[i for i,name in enumerate(self.names) if name.strip()==desired]
            if enabled and desired and not self.preferred_probed and len(matches)==1:
                self.preferred_probed=True
                p.locator('.index__view .el-card.box-card h1:visible').nth(matches[0]).click(timeout=1500)
                self.names=[desired];self.index=0;self.phase='resume';self.ready_since=None
                return 'DISCOVERING'
            if self.index<len(self.names):
                p.locator('.index__view .el-card.box-card h1:visible').nth(self.index).click(timeout=1500)
                self.phase='detail';return 'DISCOVERING'
            choices=self.active
            selected=[c for c in choices if c['course']==preferred] if preferred else choices
            if preferred and not selected:selected=choices
            if len(selected)==1 and enabled:
                self.target=selected[0];self.entering=False;self.enter_attempts=0;self.enter_retry_at=0
                card=p.locator('.index__view .el-card.box-card h1:visible').filter(has_text=re.compile(r'^\s*'+re.escape(self.target['course'])+r'\s*$'))
                if card.count()==1:card.click(timeout=3000)
                else:p.goto(self.target['url'],wait_until='domcontentloaded')
                self.phase='enter';self.enter_at=self.clock()
                return self._enter(context)
            self.index=0;self.active=[];self.next_at=self.clock()+30
            if len(choices)>1:
                self.say('多门课程正在进行，请设置唯一的优先课程名称，或手动进入。');return 'COURSE_CHOICE_REQUIRED'
            return 'WAITING_FOR_CLASS'
        if self.phase in ('detail','resume'):
            if not u.path.startswith('/v2/web/studentLog/'):
                if self.phase=='resume':self.phase='home';self.index=0;self.active=[]
                return 'NOT_VERIFIED'
            headings=p.locator('.logs-list .studentCard:visible').filter(has_text='正在上课').locator('h2:visible')
            if not headings.count() and not p.locator('.logs-list:visible,.classroom-header-base:visible').count():return 'DISCOVERING'
            # The header can load before the actual records arrive.
            if self.ready_since is None:self.ready_since=self.clock()
            if not headings.count() and self.clock()-self.ready_since<3:return 'DISCOVERING'
            for index,title in enumerate(headings.all_text_contents()):
                record=headings.nth(index).evaluate("e=>e.closest('.studentCard').innerText")
                record=re.sub(r'正在上课|课堂已结束|课程已结束|授课已结束|直播已结束|\s+','',record)
                key=hashlib.sha256((p.url+'\n'+record).encode()).hexdigest()
                if key not in self.blocked:
                    self.active.append({'course':self.names[self.index].strip(),'url':p.url,'title':title.strip(),'record_key':key})
            if self.phase=='resume' and len(self.active)==1:
                self.target=self.active[0];self.entering=False;self.enter_attempts=0;self.enter_retry_at=0;self.phase='enter';self.enter_at=self.clock()
                return self._enter(context)
            if self.phase=='resume':self.index=0;self.active=[]
            else:self.index+=1
            self.home();self.phase='home';self.ready_since=None
            return 'DISCOVERING'
        if self.phase=='enter':return self._enter(context)

    def _enter(self,context):
        from .live import page_identity
        for page in context.pages:
            if page.is_closed():continue
            try:page_identity(page.url)
            except ValueError:continue
            self.last_course=self.target['course'];self.page=None;self.next_at=self.clock()+30;self.phase='live'
            self.last_entry=valid_entry(self.target)
            self.index=0;self.active=[];self.say('已确认课堂页面打开。');return 'ENTERING_CLASS'
        heading=self.page.locator('.logs-list .studentCard:visible').filter(has_text='正在上课').locator('h2:visible').filter(has_text=re.compile(r'^\s*'+re.escape(self.target['title'])+r'\s*$'))
        if heading.count()==1 and self.enter_attempts<3 and self.clock()>=self.enter_retry_at:
            self.enter_attempts+=1;self.enter_retry_at=self.clock()+4
            heading.click(timeout=2000);self.entering=True
            return 'ENTERING_CLASS'
        if self.clock()-self.enter_at>12:
            self.say('课堂入口未能完成跳转，将重新发现课程。')
            self.phase='home';self.entering=False;self.index=0;self.active=[]
            self.page.goto(HOME,wait_until='domcontentloaded');return 'NOT_VERIFIED'
        return 'ENTERING_CLASS'
