from pathlib import Path
import json

class YuketangAdapter:
    """Only selectors observed in the authenticated v2 student UI; no answer actions."""
    status = "PARTIAL_VERIFIED"
    capabilities = {"student_course_list":"VERIFIED_CURRENT_ACCOUNT", "student_course_detail":"VERIFIED_CURRENT_ACCOUNT", "live_class":"NOT_VERIFIED", "questions":"NOT_VERIFIED", "deadline":"NOT_VERIFIED"}
    def snapshot(self, page):
        if page is None:raise NotImplementedError("A real page is required; live questions remain NOT_VERIFIED")
        from urllib.parse import urlsplit
        u=urlsplit(page.url)
        if u.scheme!='https' or u.hostname!='www.yuketang.cn' or u.port not in (None,443):
            raise ValueError("Outside allowed Yuketang host")
        if u.path.startswith('/lesson/fullscreen/v3/'):
            from .live import LiveReadOnlyAdapter
            snapshot=LiveReadOnlyAdapter().snapshot(page)
            snapshot.update(detection_status=snapshot['state'],course_active=None,
                capabilities={**self.capabilities,'live_visible_state':'PARTIAL_VERIFIED',
                              'image_question_content':'REQUIRES_REVIEW'})
            return snapshot
        data=page.evaluate("""() => {
            const visible=e=>!!(e && e.getClientRects().length && getComputedStyle(e).visibility!=='hidden');
            const text=e=>visible(e)?e.innerText.trim():'';
            const all=s=>Array.from(document.querySelectorAll(s)).filter(visible);
            const active=all('.index__view .el-tabs__item.is-active').map(e=>text(e));
            const detail=all('.classroom-header-base')[0];
            const courses=all('.index__view .el-card.box-card').map(e=>({name:text(e.querySelector('h1')),class_name:text(e.querySelector('.className'))})).filter(e=>e.name);
            return {active_tabs:active,courses:active.includes('我听的课')?courses:[],
                detail_present:!!detail,
                course_name:detail?text(detail.querySelector('.title-line .classroom-ellipsis:not(.classroom-title-tag) .title-inner-wrapper')):'',
                class_name:detail?text(detail.querySelector('.title-line .classroom-title-tag .title-inner-wrapper')):'',
                tabs:all('.rain-tabs__nav-item-text').map(e=>text(e)),
                historical_log_count:all('.logs-list section.studentCard .activity__wrap').length};
        }""")
        detail=u.path.startswith('/v2/web/studentLog/') and data['detail_present'] and bool(data['course_name']) and '学习日志' in data['tabs']
        student='我听的课' in data['active_tabs']
        teacher='我教的课' in data['active_tabs']
        import time
        return {"page_state":"STUDENT_COURSE_DETAIL" if detail else "STUDENT_COURSE_LIST" if student else "TEACHER_VIEW" if teacher else "NOT_VERIFIED",
            "login_state":"SIGNED_IN_UI" if detail or student or teacher else "NOT_VERIFIED",
            "courses":data['courses'],"selected_course":{"name":data['course_name'],"class_name":data['class_name']} if detail else None,
            "historical_log_count":data['historical_log_count'] if detail else 0,
            "course_active":None,"course_status":"NOT_VERIFIED","question":None,"deadline":None,
            "detection_status":"NOT_VERIFIED","observed_at":time.time(),"capabilities":dict(self.capabilities)}

class MockAdapter:
    def __init__(self, url):
        from urllib.parse import urlparse
        p=urlparse(url)
        if p.hostname != "127.0.0.1" or p.scheme != "http":
            raise ValueError("Mock adapter requires loopback HTTP")
        self.origin=f"{p.scheme}://{p.netloc}"
    def snapshot(self, page):
        if not page.url.startswith(self.origin + "/"): raise ValueError("Mock origin changed")
        return page.evaluate("window.classroomState || {online:false}")

    def submit(self,page,result):
        from urllib.parse import urlsplit
        # Exact origin, explicit Mock adapter and formal container; never real URLs.
        a=urlsplit(page.url);b=urlsplit(self.origin)
        if (a.scheme,a.hostname,a.port)!=(b.scheme,b.hostname,b.port):raise ValueError('Mock origin mismatch')
        s=self.snapshot(page);raw=s.get('question') or {}
        import time
        from .core import detect
        from .ai import validate
        if not s.get('online') or time.time()-s.get('observed_at',0)>3 or raw.get('deadline',0)<=time.time() or raw.get('id')!=result.get('question_instance_id'):raise ValueError('Stale mock question')
        _,q=detect(s)
        if q is None:raise ValueError('Mock question unavailable')
        answer=validate(q,result)['suggested_answer']
        container=page.locator('#exercise[data-formal="exercise"]')
        if container.get_attribute('data-instance')!=q.instance_id:raise ValueError('Mock DOM instance mismatch')
        if q.kind=='blank':
            for i,text in enumerate(answer):container.locator('input').nth(i).fill(text)
        else:
            inputs=container.locator('input')
            for i in range(inputs.count()):
                control=inputs.nth(i)
                if chr(65+i) in answer:control.check()
                elif q.kind=='multiple':control.uncheck()
        container.locator('#mock-submit').click()
        page.wait_for_function("id => window.classroomState?.question?.id===id && window.classroomState.question.submitted",arg=q.instance_id,timeout=5000)
        return self.snapshot(page)['question']['receipt']

class Browser:
    def __init__(self, profile, headless=True):
        self.profile=Path(profile).resolve(); self.headless=headless
        self.pw=None; self.context=None
        # Only profiles explicitly marked as RainClass dedicated directories.
        if self.profile.name != "rainclass-edge-profile": raise ValueError("Dedicated RainClass profile required")
    def open(self, url):
        from playwright.sync_api import sync_playwright
        self.pw=sync_playwright().start()
        try:
            self.context=self.pw.chromium.launch_persistent_context(str(self.profile),channel="msedge",headless=self.headless,chromium_sandbox=True,
                no_viewport=not self.headless,args=["--start-maximized"] if not self.headless else [])
            self.page=self.context.pages[0] if self.context.pages else self.context.new_page()
            self.context.add_init_script("""window.__rainRevision=0;addEventListener('DOMContentLoaded',()=>{if(document.body)new MutationObserver(()=>window.__rainRevision++).observe(document.body,{subtree:true,childList:true,characterData:true,attributes:true});});""")
            self.page.goto(url,wait_until='domcontentloaded')
            return self.page
        except Exception:
            self.close(); raise
    def close(self):
        context, pw = self.context, self.pw
        self.context = self.pw = None
        try:
            if context is not None: context.close()
        finally:
            if pw is not None: pw.stop()

    def alive(self):
        try:
            if not self.context or not self.context.pages:return False
            self.context.pages[0].evaluate('1')
            return True
        except Exception:return False
