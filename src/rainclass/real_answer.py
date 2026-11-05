"""Guarded real-page answer actions, executed only by the owning browser thread."""
import json
import re
import time
from .ai import validate
from .real_analysis import question
from .live import LiveReadOnlyAdapter


class AnswerStopped(Exception):
    pass


def selected(node):
    return node.evaluate("""e => {
      const radio=e.matches('input')?e:e.querySelector('input[type=radio],input[type=checkbox]');
      if(radio)return radio.checked;
      for(const name of ['aria-checked','aria-selected']){
        if(e.hasAttribute(name))return e.getAttribute(name)==='true';
      }
      if(e.matches('.options-label'))return Array.from(e.classList).some(x=>['selected','active','checked','is-checked','is-selected'].includes(x));
      return null;
    }""")


class RealAnswer:
    def __init__(self, path, trace=None):
        self.trace=trace or (lambda **kwargs:None)
        self.stage='准备'
        self.path=path
        try:self.attempts=json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:self.attempts={}
        # Corrupt submission records must not silently permit a second submit.
        if not isinstance(self.attempts,dict):raise ValueError('提交记录异常，请人工核实')

    def record(self,key,status):
        self.attempts[key]=status
        temp=self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.attempts),encoding='utf-8');temp.replace(self.path)

    def execute(self,page,draft,result,guard,submit=True):
        self.stage='核实当前题目'
        try:return self._execute(page,draft,result,guard,submit)
        except AnswerStopped:raise
        except Exception as error:
            from .follow import click_failure
            reason=click_failure(error)
            attempted=draft.instance_key in self.attempts
            self.trace(stage=self.stage,error=type(error).__name__,reason=reason,submit_attempted=attempted)
            prefix='已尝试提交，结果未知，不自动重试' if attempted else '尚未点击提交'
            raise AnswerStopped(f'{self.stage}失败（{reason}）；{prefix}。') from None

    def step(self,name):
        self.stage=name
        self.trace(stage=name)

    def click(self,node,check):
        from .follow import READINESS_SCRIPT
        node.scroll_into_view_if_needed(timeout=1200)
        check()
        ready=node.evaluate(READINESS_SCRIPT)
        self.trace(stage=self.stage,actionability={k:ready[k] for k in ('connected','visible','enabled','hit','width','height','page_hidden')})
        if not all(ready[k] for k in ('connected','visible','enabled','hit')):
            raise AnswerStopped(f'{self.stage}：控件被遮挡、不可见或不可用；尚未点击此控件，请检查学生 Edge。')
        node.click(position={'x':ready['x'],'y':ready['y']},timeout=1500)

    def open_blank(self,node,check):
        from .follow import READINESS_SCRIPT
        check()
        ready=node.evaluate(READINESS_SCRIPT)
        self.trace(stage=self.stage,phase='before_scroll',actionability={k:ready[k] for k in ('connected','visible','enabled','hit','width','height','page_hidden')})
        if not all(ready[k] for k in ('connected','visible','enabled','hit')):
            self.step('滚动定位填空作答入口')
            node.scroll_into_view_if_needed(timeout=1500)
            check();ready=node.evaluate(READINESS_SCRIPT)
        if not all(ready[k] for k in ('connected','visible','enabled','hit')):
            raise AnswerStopped('填空作答入口不可见、被遮挡或不可用，尚未点击提交')
        self.step('点击填空作答入口')
        check()
        node.click(position={'x':ready['x'],'y':ready['y']},timeout=1500)

    def _execute(self,page,draft,result,guard,submit=True):
        key=draft.instance_key
        if key in self.attempts:raise AnswerStopped('本题已有提交尝试记录，禁止重复提交，请人工核实')
        validate(question(draft,'validated'),result)
        def check():
            guard()
            snap=LiveReadOnlyAdapter().snapshot(page)
            if snap['state']!='ACTIVE_EXERCISE' or (snap.get('exercise') or {}).get('instance_key')!=key:
                raise AnswerStopped('题目已变化、结束或无法核实，已停止自动作答')
            if snap['exercise']['remaining_seconds']<2:raise AnswerStopped('剩余时间不足，已停止自动作答')
        check()
        self.step('定位答题区域')
        root=page.locator('.slide__cmp .slide__wrap:visible')
        if root.count()!=1:raise AnswerStopped('答题区域不唯一')
        root=root.element_handle()
        if re.search(r'已提交|提交成功',root.inner_text()):
            raise AnswerStopped('页面已显示提交记录，本次不重复作答')
        # Fixed handles prevent nth selectors from silently moving to a new question.
        self.step('读取选项与选中状态')
        labels=root.query_selector_all('.options-label')
        labels=[n for n in labels if n.is_visible()]
        answers=result['suggested_answer']
        if draft.kind in ('single','multiple'):
            if len(labels)!=len(draft.options) or [n.inner_text().strip() for n in labels]!=[chr(65+i) for i in range(len(labels))]:
                raise AnswerStopped('页面选项与已核对选项数量或顺序不一致')
            before=[selected(n) for n in labels]
            if any(v is None for v in before):raise AnswerStopped('无法核实页面选项状态')
            wanted=[chr(65+i) in answers for i in range(len(labels))]
            for i,node in enumerate(labels):
                check()
                # A single radio selection clears the previous selection itself.
                if selected(node)!=wanted[i] and (draft.kind=='multiple' or wanted[i]):
                    self.step('选择选项 '+chr(65+i))
                    self.click(node,check)
                    check()
            if [selected(n) for n in labels]!=wanted:raise AnswerStopped('选项回读与 AI 答案不一致，未提交')
        elif draft.kind in ('blank','essay'):
            from .blank_panel import fields as blank_fields,panel,ordered_fields
            self.step('定位填空作答面板')
            drawer=panel(page,draft.kind)
            if drawer is None and not blank_fields(root):
                openers=[n for n in root.query_selector_all('.submit-btn,button,[role=button]') if n.is_visible() and n.inner_text().strip()=='作答']
                if len(openers)!=1:raise AnswerStopped('没有找到唯一的填空作答入口，尚未填写或提交')
                self.step('打开填空作答面板');self.open_blank(openers[0],check)
                until=time.monotonic()+3
                while time.monotonic()<until:
                    check();drawer=panel(page,draft.kind)
                    if drawer is not None:break
                    page.wait_for_timeout(100)
                if drawer is None:raise AnswerStopped('填空作答面板尚未就绪，尚未填写或提交')
            if drawer is not None:root=drawer
            fields=ordered_fields(root)
            count=len(fields) if fields is not None else -1
            self.trace(stage='核实填空映射',control_types=root.evaluate("e=>Array.from(e.querySelectorAll('input,textarea,[contenteditable]')).slice(0,20).map(n=>({tag:n.tagName,type:n.getAttribute('type'),editable:n.getAttribute('contenteditable')}))"),reviewed_blanks=draft.blank_count,answer_count=len(answers),editor_count=count,separate_panel=drawer is not None)
            if fields is None:raise AnswerStopped('填空编号缺失、重复或不连续，未填写或提交')
            if draft.kind=='essay' and count!=1:raise AnswerStopped(f'主观题需要唯一编辑器，页面可填写编辑器 {count} 个；未填写或提交')
            if count!=(1 if draft.kind=='essay' else draft.blank_count):raise AnswerStopped(f'填空映射不一致：已核对 {draft.blank_count} 空，AI 答案 {len(answers)} 项，页面可填编辑器 {count} 个；未填写或提交')
            if draft.kind=='essay':
                limit=fields[0].evaluate('e=>e.maxLength>0?Math.min(e.maxLength,1000):1000')
                if len(answers[0].encode('utf-16-le'))//2>limit:raise AnswerStopped(f'主观题答案超过页面 {limit} 字限制，未填写或提交')
            for index,(node,text) in enumerate(zip(fields,answers)):
                self.step('填写第 '+str(index+1)+' 空')
                check();node.fill(text,timeout=1500);node.press('Tab',timeout=1500);check()
                value=node.evaluate("e => e.isContentEditable?e.innerText:e.value")
                if value.strip()!=text.strip():raise AnswerStopped('填空回读不一致，未提交')
        else:raise AnswerStopped('暂不支持本题型自动作答')
        check()
        if not submit:
            self.record(key,'FILLED_ONLY')
            return 'AI 答案已填写，未点击提交，请自行核对并提交'
        self.step('定位提交按钮')
        buttons=[n for n in root.query_selector_all('button,[role=button],.submit-btn' if draft.kind in ('blank','essay') else '.submit-btn') if n.is_visible() and n.inner_text().strip()=='提交答案']
        if len(buttons)!=1 or not buttons[0].is_enabled():raise AnswerStopped('未找到唯一可用的提交答案按钮')
        # Durable mark precedes the irreversible click. Unknown outcomes never retry.
        self.step('提交前检查')
        from .follow import READINESS_SCRIPT
        check()
        ready=buttons[0].evaluate(READINESS_SCRIPT)
        self.trace(stage=self.stage,phase='before_scroll',actionability={k:ready[k] for k in ('connected','visible','enabled','hit','width','height','page_hidden')})
        # A visible drawer footer need not scroll. In a background/transitioning
        # page, Playwright's scroll stability wait can time out on that same node.
        if not all(ready[k] for k in ('connected','visible','enabled','hit')):
            self.step('滚动定位提交按钮')
            buttons[0].scroll_into_view_if_needed(timeout=1200)
            check()
            ready=buttons[0].evaluate(READINESS_SCRIPT)
            self.trace(stage=self.stage,phase='after_scroll',actionability={k:ready[k] for k in ('connected','visible','enabled','hit','width','height','page_hidden')})
        if not all(ready[k] for k in ('connected','visible','enabled','hit')):raise AnswerStopped('提交按钮不可点击，尚未点击提交')
        check()
        self.record(key,'ATTEMPTED_UNKNOWN')
        self.step('点击提交按钮')
        check()
        buttons[0].click(position={'x':ready['x'],'y':ready['y']},timeout=1500)
        self.step('等待提交回执')
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            guard()
            # A new route is never evidence that the old question was submitted.
            from .live import page_identity
            import hashlib
            identity=page_identity(page.url)
            if hashlib.sha256('/'.join(identity).encode()).hexdigest()!=key:break
            if root.is_visible() and re.search(r'已提交|提交成功',root.inner_text()):
                self.record(key,'CONFIRMED');return '已填写并提交，页面显示提交成功/已提交'
            page.wait_for_timeout(100)
        return '已点击提交，但未获得明确回执；状态未知，请人工核实，不会自动重试'
