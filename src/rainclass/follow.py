"""Follow newly published visible exercise cards, without touching answer controls."""
import hashlib
import json
import time
from .live import page_identity
from .focus_guard import background_action

CARDS='.timeline__ppt.problem:visible'
CARD_SCRIPT=r'''cards => cards.map(e => {
 const link=e.matches('a[href]')?e:Array.from(e.querySelectorAll('a[href]')).find(a=>{
   try {const u=new URL(a.href);return u.origin==='https://www.yuketang.cn'&&u.pathname.startsWith('/lesson/fullscreen/v3/');}catch{return false;}
 });
 const attrs=Array.from(e.attributes).filter(a=>a.name==='id'||/^data-(?:.*-)?(?:id|key|uuid)$/.test(a.name))
   .map(a=>[a.name,a.value]).sort();
 const href=link&&!/^(?:javascript:|#)/i.test(link.getAttribute('href')||'')?link.href:null;
 const images=Array.from(e.querySelectorAll('img')).map(i=>i.getAttribute('src'));
 const text=e.innerText.replace(/(?:倒计时\s*)?\d{1,3}:\d{2}(?::\d{2})?/g,'')
   .replace(/作答已结束|正在作答|未作答|已作答|未答题|已答题|已超时|超时|未完成|已完成|已结束|作答中/g,'')
   .replace(/\d+\s*(?:人作答|人已答|人未答)/g,'').replace(/\s+/g,' ').trim();
 // Answer status is mutable. An image/link/ID, when present, identifies the card.
 return {identity:JSON.stringify(attrs.length?['id',attrs]:href?['link',href]:images.length?['images',images]:['text',text]),href};
})'''

READINESS_SCRIPT=r'''e => {
 const b=e.getBoundingClientRect();let l=Math.max(0,b.left),t=Math.max(0,b.top),
 r=Math.min(innerWidth,b.right),d=Math.min(innerHeight,b.bottom);
 for(let p=e.parentElement;p;p=p.parentElement){
   const s=getComputedStyle(p),q=p.getBoundingClientRect();
   if(/auto|scroll|hidden|clip/.test(s.overflowX)){l=Math.max(l,q.left+p.clientLeft);r=Math.min(r,q.left+p.clientLeft+p.clientWidth);}
   if(/auto|scroll|hidden|clip/.test(s.overflowY)){t=Math.max(t,q.top+p.clientTop);d=Math.min(d,q.top+p.clientTop+p.clientHeight);}
 }
 const visible=r-l>2&&d-t>2, x=(l+r)/2,y=(t+d)/2;
 const hit=visible?document.elementFromPoint(x,y):null;
 return {connected:e.isConnected,visible,enabled:!e.matches(':disabled,[aria-disabled=true]'),
   hit:!!hit&&(hit===e||e.contains(hit)),x:x-b.left,y:y-b.top,
   width:Math.round(b.width),height:Math.round(b.height),page_hidden:document.hidden};
}'''

def click_failure(error):
    message=str(error).lower()
    for token,reason in [('intercepts pointer','OBSCURED'),('not stable','ANIMATING'),
                         ('outside of the viewport','OFFSCREEN'),('not visible','NOT_VISIBLE'),
                         ('not enabled','DISABLED'),('detached','DETACHED'),('not attached','DETACHED')]:
        if token in message:return reason
    return 'TIMEOUT_UNKNOWN' if type(error).__name__=='TimeoutError' else 'CLICK_ERROR'

class ExerciseFollower:
    def __init__(self,notice,clock=time.monotonic):
        self.notice=notice;self.clock=clock;self.scope=None;self.seen=set();self.pending=None
        self.last_route=None;self.warned=set()
        self.diagnostics={}
        self.max_refreshes=2

    def reset(self):
        self.scope=None;self.seen.clear();self.pending=None;self.last_route=None;self.warned.clear()
        self.diagnostics={}

    def _arrived(self,route,target):
        if route[0]!=target['before'][0] or route[1] not in ('exercise','blank','subjective'):return False
        expected=target['expected']
        if expected and expected!=target['before'] and expected[1] in ('exercise','blank','subjective'):
            return route==expected
        return route!=target['before']

    def _click(self,page,card,record,target):
        """Normal pointer action on the same DOM node, never force/JS dispatch."""
        node=None
        try:
            node=card.element_handle(timeout=500)
            if node is None:raise RuntimeError('detached')
            if node.evaluate('e => ('+CARD_SCRIPT+')([e])[0].identity')!=record['identity']:
                target['reason']='REPLACED';return
            before=node.evaluate(READINESS_SCRIPT)
            self.diagnostics['before_scroll']={k:before[k] for k in ('connected','visible','enabled','hit','width','height','page_hidden')}
            node.scroll_into_view_if_needed(timeout=800)
            ready=node.evaluate(READINESS_SCRIPT)
            self.diagnostics['actionability']={k:ready[k] for k in ('connected','visible','enabled','hit','width','height','page_hidden')}
            if not ready['connected']:target['reason']='DETACHED';return
            if not ready['visible']:target['reason']='OFFSCREEN';return
            if not ready['enabled']:target['reason']='DISABLED';return
            if not ready['hit']:target['reason']='OBSCURED';return
            # A rerender during scrolling must not turn an nth locator into a
            # click on a different publication. The handle pins this node.
            if node.evaluate('e => ('+CARD_SCRIPT+')([e])[0].identity')!=record['identity']:
                target['reason']='REPLACED';return
            target['attempts']+=1
            with background_action(page,self.diagnostics):
                node.click(position={'x':ready['x'],'y':ready['y']},timeout=1200)
            target['reason']='DISPATCHED'
        except Exception as error:
            target['reason']=click_failure(error)
            self.diagnostics['click_error']=type(error).__name__
        finally:
            if node is not None:
                try:node.dispose()
                except Exception:pass
        # A click can time out after the SPA already navigated. Do not click it
        # again before checking that observable result on the next poll.
        try:
            if self._arrived(page_identity(page.url),target):target['observed']=True
        except (ValueError,TypeError):pass

    def _restore(self,page,target,now):
        expected=target['expected']
        if (not target['fallback'] and expected and expected!=target['before']
                and expected[1] in ('exercise','blank','subjective')):
            target['fallback']=True;target['next']=now+3
            self.diagnostics['phase']='LINK_FALLBACK'
            self.notice('题卡未完成切换，尝试打开已确认的新题链接。')
            try:
                with background_action(page,self.diagnostics):
                    page.goto(target['href'],wait_until='domcontentloaded',timeout=5000)
            except Exception as error:target['reason']=click_failure(error)
            return True
        limit=max(0,min(5,self.max_refreshes))
        if target['refreshes']<limit:
            target['refreshes']+=1;target['attempts']=0;target['checks']=0
            target['loading_since']=None;target['next']=now+2
            self.diagnostics.update(phase='REFRESHING',refreshes=target['refreshes'])
            self.notice(f"新题仍未就绪，正在进行第 {target['refreshes']}/{limit} 次页面同步；保留新题目标。")
            try:
                with background_action(page,self.diagnostics):
                    page.reload(wait_until='domcontentloaded',timeout=5000)
            except Exception as error:target['reason']=click_failure(error)
            return True
        return False

    def poll(self,page,snapshot,enabled=True):
        """Return True while a new-card navigation has not yet been verified."""
        route=page_identity(page.url)
        scope=(id(page),route[0])
        cards=page.locator(CARDS)
        records=cards.evaluate_all(CARD_SCRIPT)
        bases=[hashlib.sha256(r['identity'].encode()).hexdigest() for r in records]
        occurrences={};keys=[]
        for base in bases:
            index=occurrences.get(base,0);occurrences[base]=index+1
            keys.append(f'{base}:{index}')
        if scope!=self.scope:
            self.reset();self.scope=scope;self.seen.update(keys);self.last_route=route
            self.diagnostics={'phase':'BASELINE','cards':len(keys)}
            return False
        self.diagnostics={'phase':'IDLE','cards':len(keys),'attempts':0}
        new=set(keys)-self.seen
        self.seen.update(keys)
        if not enabled:
            self.pending=None;self.last_route=route;return False
        if new:
            candidates=[i for i,k in enumerate(keys) if k in new]
            if candidates and candidates[-1]==len(keys)-1:
                # The observed timeline appends publications chronologically. A batch
                # can contain overdue/unanswered cards; follow the newest publication.
                index=candidates[-1];expected=None
                try:expected=page_identity(records[index]['href'])
                except (ValueError,TypeError,AttributeError):pass
                if records[index]['href'] and (not expected or expected[0]!=route[0]):
                    self.notice('新习题卡链接无法确认为当前课堂，未自动切换。');self.pending=None
                else:
                    already_moved=(route!=self.last_route and route[1] in ('exercise','blank','subjective')
                        and (expected is None or expected==route or expected[1]=='ppt'))
                    self.pending={'key':keys[index],'before':route,'expected':expected,
                        'href':records[index]['href'],'attempts':0,'next':0,'fallback':False,'arrived':False,
                        'observed':already_moved,'checks':0,'refreshes':0,'deadline':self.clock()+40,
                        'loading_since':None,'reason':'NEW_TARGET'}
                    if already_moved:self.pending['before']=self.last_route
        target=self.pending
        if target:
            now=self.clock()
            self.diagnostics.update(phase='FOLLOWING',attempts=target['attempts'],refreshes=target['refreshes'],
                                    checks=target['checks'],click_reason=target['reason'])
            # A card's href may name a PPT while its Vue handler opens an exercise.
            # Confirm the actual same-lesson exercise route after at least one click;
            # a link equal to the old route is not evidence that a new card opened.
            matched=((target['attempts']>0 or target.get('observed') or target['fallback'] or target['refreshes']>0)
                     and self._arrived(route,target))
            if matched and snapshot['state'] in ('ACTIVE_EXERCISE','CLOSED_EXERCISE'):
                self.pending=None;self.last_route=route
                self.diagnostics['phase']='VERIFIED'
                self.notice('已跟随新习题，课堂主区域已更新。');return False
            if now>=target['deadline']:
                self.pending=None;self.last_route=route;self.diagnostics['phase']='UNCONFIRMED'
                self.notice('新题恢复已达到时间上限，已停止自动操作；请查看切题诊断。');return False
            if matched:
                # Navigation succeeded. Re-clicking while the image loads can restart
                # that load repeatedly and consume the new question's time limit.
                self.last_route=route
                self.diagnostics['phase']='CONTENT_LOADING'
                if not target['arrived']:
                    target['arrived']=True
                    self.notice('已切换至新题，等待题目内容加载。')
                if target['loading_since'] is None:target['loading_since']=now
                if now>=target['next'] and now-target['loading_since']>=8:
                    if not self._restore(page,target,now):
                        self.pending=None;self.diagnostics['phase']='UNCONFIRMED'
                        self.notice('新题内容多次同步后仍未就绪，已停止自动操作；请查看切题诊断。')
                # Keep tracking until content is verified: the SPA can fall back
                # to PPT during loading. It still has the original retry budget.
                return False
            if now>=target['next']:
                if target['attempts']>=3 or target['checks']>=3:
                    if self._restore(page,target,now):return True
                    self.pending=None;self.last_route=route
                    self.diagnostics['phase']='UNCONFIRMED'
                    self.notice('新习题切换未确认，已停止重试；请手动点击习题卡或恢复课堂。')
                    return False
                matches=[i for i,k in enumerate(keys) if k==target['key']]
                target['checks']+=1;target['next']=now+2
                if len(matches)==1:
                    self._click(page,cards.nth(matches[0]),records[matches[0]],target)
                else:target['reason']='TARGET_NOT_PRESENT'
                self.diagnostics.update(attempts=target['attempts'],checks=target['checks'],click_reason=target['reason'])
            return True
        self.last_route=route
        return False
