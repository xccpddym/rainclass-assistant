"""Dedicated real-classroom UI worker: monitoring and explicitly enabled answer actions; no model clients."""
import json
import time
import uuid
import re
import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from queue import Queue,Empty
from urllib.parse import urlsplit
from PySide6.QtCore import QThread,Signal
from .browser import Browser
from .live import LiveReadOnlyAdapter,LiveReadOnlyMonitor,page_identity
from .real_review import load_seen,save_seen
from .question_ocr import LAYOUT_SCRIPT,recognize_question
from .follow import ExerciseFollower
from .discovery import CourseDiscovery,valid_entry,HOME
from .direct_discovery import DirectCourseDiscovery

IMAGE_REVISION_SCRIPT='''img => ({ready:img.complete && img.naturalWidth>0 && img.naturalHeight>0,
    source:img.currentSrc || img.src,width:img.naturalWidth,height:img.naturalHeight})'''

def image_revision(image):
    if image.count()!=1:return None
    version=image.evaluate(IMAGE_REVISION_SCRIPT)
    if not version.get('ready'):return None
    return hashlib.sha256(json.dumps(version,sort_keys=True).encode()).hexdigest()

def official(url):
    u=urlsplit(url)
    return u.scheme=='https' and u.hostname=='www.yuketang.cn' and u.port in (None,443) and not(u.username or u.password)

def live_page(context,ended=None):
    pages=[]
    for page in context.pages:
        if page.is_closed():continue
        try:
            identity=page_identity(page.url)
            if ended and hashlib.sha256(identity[0].encode()).hexdigest() in ended:continue
        except ValueError:continue
        pages.append(page)
    if len(pages)==1:return pages[0]
    if pages and len({page_identity(p.url)[0] for p in pages})==1:return pages[-1]
    return None

class RealWorker(QThread):
    answer_status=Signal(str)
    status=Signal(dict)
    preview=Signal(dict)
    new_question=Signal(str)
    alert=Signal(str)
    notice=Signal(str)
    def __init__(self,profile,data_dir):
        super().__init__()
        self.profile=Path(profile);self.data_dir=Path(data_dir)
        self.answer_queue=Queue(maxsize=1)
        self.stopping=Event();self.paused=Event();self.capture_request=Event();self.recover_request=Event()
        self.follow_enabled=Event();self.follow_enabled.set()
        self.monitor=LiveReadOnlyMonitor()
        self.monitor.seen=load_seen(self.data_dir/'real-seen.json')
        self.follower=ExerciseFollower(self.notice.emit)
        self.refresh_limit=2
        self.auto_enter=Event();self.auto_enter.set();self.preferred_course=''
        self.silent_recovery=Event()
        self.ended_lessons=load_seen(self.data_dir/'ended-lessons.json')
        self.ended_entries=load_seen(self.data_dir/'ended-entry-keys.json')
        try:self.last_entry=valid_entry(json.loads((self.data_dir/'last-class-entry.json').read_text(encoding='utf-8')))
        except (OSError,ValueError):self.last_entry=None

    def recovery_log(self,event,attempt):
        self.data_dir.mkdir(parents=True,exist_ok=True)
        with (self.data_dir/'browser-recovery.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps({'time_unix':time.time(),'event':event,'attempt':attempt})+'\n')

    def question_trace(self,event,**values):
        """Stage evidence only: no question text, images, URLs or credentials."""
        try:
            with (self.data_dir/'real-question-diagnostics.jsonl').open('a',encoding='utf-8') as f:
                f.write(json.dumps({'time_unix':time.time(),'event':event,**values})+'\n')
        except OSError:pass

    def _recover(self,context,page):
        if page is not None:
            page.reload(wait_until='domcontentloaded',timeout=10000)
            self.notice.emit('已重新同步课堂，已见题目记录保留。')
        else:self.notice.emit('将重新查询正在上课状态。')

    def run(self):
        from .real_answer import RealAnswer,AnswerStopped
        try:answerer=RealAnswer(self.data_dir/'real-submit-attempts.json',trace=lambda **values:self.question_trace('ANSWER_STAGE',**values))
        except Exception:
            answerer=None
            self.notice.emit('提交记录不可读取，自动作答已停用；题目监测继续。')
        capture_token=None
        browser=None;launches=0;opened=False;original_course='';launch_failures=0
        pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='local-ocr')
        def warm_ocr():
            try:
                from .question_ocr import _rapid,_lock
                with _lock:_rapid()
            except Exception:pass
        pool.submit(warm_ocr)
        future=None;pending=None;queued=None;current_key=None;captured=None;captured_revision=None;retry_at=0;thresholds=set();last_diag=None;shell_wait={};last_question_diag=None
        try:
            adapter=LiveReadOnlyAdapter()
            discovery=DirectCourseDiscovery(self.notice.emit,self.ended_lessons,self.stopping)
            while not self.stopping.is_set():
                alive=opened and (browser.alive() if hasattr(browser,'alive') else bool(browser.context.pages))
                if not alive:
                    if opened:self.recovery_log('browser_unavailable',launches-1)
                    current_key=None;captured=None;queued=None
                    self.status.emit({'state':'RECOVERING','instance_key':None})
                    if self.paused.is_set():
                        self.stopping.wait(.5);continue
                    if launch_failures>=6:
                        self.notice.emit('浏览器连续启动失败已达到重试上限，请手动重新启动监测。');break
                    if launches and self.stopping.wait(min(30,2**launch_failures)):break
                    if self.stopping.is_set():break
                    if browser:
                        try:browser.close()
                        except Exception:pass
                    browser=Browser(self.profile,headless=launches>0 and self.silent_recovery.is_set())
                    launches+=1;opened=False
                    self.recovery_log('launch' if launches==1 else 'relaunch',launches-1)
                    try:
                        browser.open(HOME);opened=True;launch_failures=0
                        discovery=DirectCourseDiscovery(self.notice.emit,self.ended_lessons,self.stopping);self.follower.reset()
                        self.recovery_log('connected',launches-1)
                    except Exception:
                        launch_failures+=1
                        self.recovery_log('launch_failed',launches-1);continue
                    if self.stopping.is_set():break
                page=live_page(browser.context,self.ended_lessons)
                if self.paused.is_set():
                    current_key=None;captured=None
                    self.status.emit({'state':'PAUSED','instance_key':None})
                else:
                    try:
                        recovering=self.recover_request.is_set()
                        if recovering:
                            self.recover_request.clear()
                            discovery.next_at=0
                            discovery.entry_tries.clear()
                            if page is None:
                                self._recover(browser.context,page);self.follower.reset();captured=None
                        if page is None:
                            state=discovery.tick(browser.context,self.auto_enter.is_set(),self.preferred_course or original_course)
                            (self.data_dir/'discovery-state.json').write_text(json.dumps({'source':'on_lesson_query','state':state,'phase':discovery.phase,'active_count':len(discovery.active),'auto_enter':self.auto_enter.is_set(),'login_state':discovery.login_state,'last_query_at':discovery.last_query_at}),encoding='utf-8')
                            original_course=discovery.last_course or original_course
                            snap={'state':state,'exercise':None}
                        else:
                            ended_marker=page.locator('body').get_by_text(re.compile(r'^\s*(?:本次|本节|该)?\s*(?:课堂|课程|授课|直播)\s*(?:已经|已)?结束[！!。.，,\s]*(?:(?:请|谢谢|感谢).*)?$')).filter(visible=True)
                            ended_visible=bool(ended_marker.count())
                            current_status=None if ended_visible else discovery.check_current(page,force=recovering)
                            if ended_visible or current_status is False:
                                ended_lesson=page_identity(page.url)[0]
                                if discovery.phase=='enter':discovery._enter(browser.context)
                                self.ended_lessons.add(hashlib.sha256(page_identity(page.url)[0].encode()).hexdigest())
                                discovery.mark_ended();self.last_entry=None;original_course=''
                                save_seen(self.data_dir/'ended-lessons.json',self.ended_lessons)
                                save_seen(self.data_dir/'ended-entry-keys.json',self.ended_entries)
                                (self.data_dir/'last-class-entry.json').write_text('null',encoding='utf-8')
                                self.follower.reset();current_key=None;captured=None;queued=None
                                for old_page in list(browser.context.pages):
                                    if old_page.is_closed():continue
                                    try:old_lesson=page_identity(old_page.url)[0]
                                    except ValueError:continue
                                    if old_lesson==ended_lesson:old_page.close()
                                self.status.emit({'state':'WAITING_FOR_CLASS','instance_key':None});continue
                            if recovering:
                                if current_status is True:
                                    self._recover(browser.context,page);self.follower.reset();captured=None
                                else:self.notice.emit('当前课堂是否仍在上课尚未确认，继续检查，暂不重新加载旧课堂。')
                            if page_identity(page.url)[1]=='pending':
                                marker=(id(page),page_identity(page.url)[0])
                                since=shell_wait.setdefault(marker,time.monotonic())
                                if time.monotonic()-since>5:
                                    shell_wait[marker]=float('inf')
                                    page.reload(wait_until='domcontentloaded',timeout=10000)
                                    self.notice.emit('课堂入口尚未同步，已进行一次页面重新同步。')
                            if discovery.phase=='enter':
                                discovery._enter(browser.context);original_course=discovery.last_course or original_course
                            snap=adapter.snapshot(page)
                            self.follower.max_refreshes=self.refresh_limit
                            if self.follower.poll(page,snap,self.follow_enabled.is_set()):
                                snap={**snap,'state':'FOLLOWING_EXERCISE','exercise':None}
                            detail={'state':snap['state'],'structure':snap.get('structure',{}),'follow':self.follower.diagnostics}
                            detail_signature=json.dumps(detail,sort_keys=True)
                            if detail_signature!=last_question_diag:
                                self.question_trace('OBSERVATION',**detail);last_question_diag=detail_signature
                        if discovery.last_entry and discovery.last_entry!=self.last_entry:
                            self.last_entry=discovery.last_entry
                            (self.data_dir/'last-class-entry.json').write_text(json.dumps(self.last_entry,ensure_ascii=False),encoding='utf-8')
                        raw=snap.get('exercise') or {}
                        active=snap['state']=='ACTIVE_EXERCISE'
                        key=raw.get('instance_key') if active else None
                        if key!=current_key:retry_at=0
                        current_key=key
                        if key is None:captured=None
                        state={k:v for k,v in raw.items() if k in ('remaining_seconds','question_type','option_count')}
                        lesson_key=hashlib.sha256(page_identity(page.url)[0].encode()).hexdigest() if page is not None else None
                        state.update(state=snap['state'],instance_key=key,lesson_key=lesson_key,events=len(self.monitor.events),ai_requests=0,submissions=sum(v=='CONFIRMED' for v in answerer.attempts.values()) if answerer else 0)
                        state.update(login_state=discovery.login_state,active_count=len(discovery.active),auto_enter=self.auto_enter.is_set(),last_query_at=discovery.last_query_at)
                        self.status.emit(state)
                        event=self.monitor.observe(snap)
                        if event:
                            try:save_seen(self.data_dir/'real-seen.json',self.monitor.seen)
                            except OSError:self.notice.emit('去重记录保存失败，本次运行仍可去重。')
                            self.new_question.emit({'blank':'填空题','essay':'主观题'}.get(raw['question_type'],'互动题'))
                        if active:
                            for threshold in (30,20,10):
                                marker=(key,threshold)
                                if raw['remaining_seconds']<=threshold and marker not in thresholds:
                                    thresholds.add(marker);self.alert.emit(f'真实课堂剩余不足 {threshold} 秒，请留意。')
                        capture=self.capture_request.is_set();self.capture_request.clear()
                        revision=None
                        if key and time.monotonic()>=retry_at:
                            try:
                                image=page.locator('.slide__cmp .slide__wrap img.cover:visible')
                                revision=image_revision(image)
                                if revision is None:
                                    retry_at=time.monotonic()+1
                                    if key!=captured:self.question_trace('IMAGE_LOADING',key=key)
                            except Exception as error:
                                retry_at=time.monotonic()+1
                                self.question_trace('IMAGE_CHECK_FAILED',key=key,error=type(error).__name__)
                        if revision and (key!=captured or revision!=captured_revision or capture):
                            try:
                                self.question_trace('CAPTURE_START',key=key)
                                if image.count()!=1:raise ValueError('Image unavailable')
                                layout=image.evaluate(LAYOUT_SCRIPT)
                                capture_started=time.monotonic()
                                content=image.screenshot(timeout=1500,animations='disabled')
                                check=adapter.snapshot(page)
                                if check['state']!='ACTIVE_EXERCISE' or (check.get('exercise') or {}).get('instance_key')!=key or image_revision(image)!=revision:
                                    self.question_trace('CAPTURE_STALE',key=key)
                                    raise ValueError('Question changed during capture')
                                captured=key;captured_revision=revision
                                payload={'instance_key':key,'revision':uuid.uuid4().hex,'image':content,
                                         'question_type':raw['question_type'],'option_count':raw['option_count'],'ocr_text':'','ocr_pending':True}
                                capture_token=payload['revision']
                                payload['layout']=layout
                                payload['capture_ms']=round((time.monotonic()-capture_started)*1000)
                                payload['captured_at']=time.monotonic()
                                self.preview.emit(payload)
                                self.question_trace('CAPTURE_READY',key=key)
                                # At most one queued OCR job; sampling keeps running while OCR executes.
                                if future is None:
                                    pending=payload;future=pool.submit(recognize_question,content,layout,raw['question_type'])
                                else:queued=payload
                            except Exception as error:
                                self.question_trace('CAPTURE_FAILED',key=key,error=type(error).__name__)
                                retry_at=time.monotonic()+1
                                self.notice.emit('题目图片尚未就绪，1 秒后重试；也可点击恢复课堂。')
                        signature=(snap['state'],key,len(self.monitor.events))
                        if signature!=last_diag:
                            row={'time_unix':time.time(),'state':snap['state'],'events':len(self.monitor.events),'ai_requests':0,'submissions':0}
                            with (self.data_dir/'real-diagnostics.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row)+'\n')
                            last_diag=signature
                    except Exception as error:
                        current_key=None
                        self.status.emit({'state':'RECOVERING','instance_key':None})
                        self.notice.emit('读取暂不可用：'+type(error).__name__+'。可点击恢复课堂。')
                if future is not None and future.done():
                    try:
                        result=future.result()
                        timing={'time_unix':time.time(),'event':'ocr_timing','capture_ms':pending.get('capture_ms'),
                            'capture_to_result_ms':round((time.monotonic()-pending.get('captured_at',time.monotonic()))*1000),
                            'ocr_ms':result.get('ocr_ms'),'source':result.get('source','unknown')}
                        try:
                            with (self.data_dir/'real-performance.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(timing)+'\n')
                        except OSError:pass
                        if not self.paused.is_set() and current_key==pending['instance_key']:
                            self.preview.emit({**pending,'ocr_text':result['text'],'type_hint':result['kind_hint'],'candidate':result,'ocr_pending':False})
                            self.question_trace('OCR_READY',key=pending['instance_key'])
                        else:self.question_trace('OCR_STALE',key=pending['instance_key'])
                    except Exception as error:
                        self.question_trace('OCR_FAILED',key=pending['instance_key'] if pending else None,error=type(error).__name__)
                        self.notice.emit('本地 OCR 不可用，请对照原图手动填写。')
                    future=None;pending=None
                    if queued and queued['instance_key']==current_key and not self.paused.is_set():
                        pending=queued;future=pool.submit(recognize_question,queued['image'],queued['layout'],queued['question_type'])
                    queued=None
                try:command=self.answer_queue.get_nowait()
                except Empty:command=None
                if command:
                    draft,result,valid=command[:3]
                    should_submit=command[3] if len(command)>3 else True
                    try:
                        def guard():
                            if not valid.is_set() or self.stopping.is_set() or self.paused.is_set():raise AnswerStopped('自动作答已取消')
                            if page is None or current_key!=draft.instance_key or capture_token!=draft.image_revision:raise AnswerStopped('当前题目或截图已变化，已停止自动作答')
                            if image_revision(page.locator('.slide__cmp .slide__wrap img.cover:visible'))!=captured_revision:raise AnswerStopped('题图已变化，已停止自动作答')
                        guard()
                        if answerer is None:raise AnswerStopped('提交记录不可用，自动作答已停用')
                        message=answerer.execute(page,draft,result,guard,submit=should_submit)
                        self.answer_status.emit(message)
                    except Exception as error:
                        message=str(error) if isinstance(error,AnswerStopped) else '自动作答未完成或提交状态未知，请人工核实；不自动重试'
                        self.answer_status.emit(message)
                        self.question_trace('ANSWER_STOPPED',error=type(error).__name__)
                # Pump Playwright events even if the classroom is covered by other apps.
                try:browser.context.pages[0].wait_for_timeout(500)
                except Exception:
                    opened=False
        except Exception as error:
            self.status.emit({'state':'STOPPED','instance_key':None})
            self.notice.emit('真实监测启动或运行失败：'+type(error).__name__+'。请确认专用 Edge 资料未被其他进程占用。')
        finally:
            try:
                if browser:browser.close()
            except Exception:pass
            pool.shutdown(wait=True,cancel_futures=True)
            self.status.emit({'state':'STOPPED','instance_key':None})
