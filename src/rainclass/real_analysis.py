"""Reviewed text analysis only. No browser or answer-writing capability."""
import hashlib
import json
import os
import math
import threading
from .ai import CompatibleAI, AnalysisError
from .analysis import AnalysisService
from .core import Question
from .storage import Store


def question(draft, lesson_key):
    if not lesson_key:
        raise ValueError('课堂身份尚未就绪')
    if draft.kind not in ('single', 'multiple', 'blank', 'essay'):
        raise ValueError('不支持该题型')
    content = json.dumps([draft.kind, draft.stem, draft.options, draft.blank_count], ensure_ascii=False)
    if len(content.encode('utf-8')) > 60000:
        raise ValueError('题目总文本过长，请精简后重新核对')
    fingerprint = hashlib.sha256(content.encode()).hexdigest()
    return Question(draft.instance_key, 'real-lesson:' + lesson_key, draft.kind,
                    draft.stem, draft.options, draft.blank_count, fingerprint)


class RealAnalysis:
    def __init__(self, path, config, persist=True):
        profiles = config.get('profiles', [])[:2]
        if not profiles:
            raise ValueError('请先在 config.toml 配置真实 AI 模型')
        try:
            from urllib.parse import urlsplit
            for p in profiles:
                if not urlsplit(p['base_url']).hostname or not isinstance(p['model'], str) or not p['model'].strip():
                    raise ValueError()
                reserve = float(p.get('max_request_cost', .1))
                timeout = float(p.get('timeout', 20))
                if not math.isfinite(reserve) or reserve <= 0 or not math.isfinite(timeout):
                    raise ValueError()
            clients = [CompatibleAI(p) for p in profiles]
            if any(not os.environ.get(p.get('key_env', 'RAINCLASS_API_KEY')) for p in profiles):
                raise ValueError()
            # Real classrooms have no request-count cap, including old configs
            # that still contain call_limit=20. Monetary budget is independent.
            budget = None if config['budget'] is None else float(config['budget'])
            if budget is not None and not 0 < budget < float('inf'):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise ValueError('AI 配置无效：请检查地址、模型、Key 环境变量及费用上限') from None
        self.store = Store(path)
        self.service = AnalysisService(self.store, clients, persist=persist, call_limit=None, budget=budget)
        self.requests = {}; self.closing = False; self.closed = threading.Event()

    def submit(self, draft, lesson_key):
        if self.closing: raise ValueError('分析服务正在退出')
        q = question(draft, lesson_key)
        key = (q.course_id, q.instance_id, q.fingerprint)
        if key in self.requests: return self.requests[key]
        if any(not f.done() for f in self.requests.values()):
            raise ValueError('已有分析请求进行中，请等待完成')
        # Controller owns content-level dedup; bypass legacy instance-only futures.
        future = self.service.pool.submit(self.service.analyze, q, False)
        self.requests[key] = future
        return future

    def set_budget(self,value):
        if value is not None and not .1<=value<=10:raise ValueError('预算应在 0.1–10 元之间')
        self.service.budget=value
        retry=[]
        for key,future in list(self.requests.items()):
            if not future.done() or future.cancelled():continue
            error=future.exception()
            if isinstance(error,AnalysisError) and str(error) in ('单课预算已达到','Course budget reached','单课预算或调用上限已达到','Course budget/call limit reached'):
                del self.requests[key]
                if key[0]=='auto':retry.append((key[2],key[3]))
        return retry

    def close(self):
        if self.closing: return
        self.closing = True
        def cleanup():
            try:
                self.service.close()
                self.store.close()
            finally: self.closed.set()
        threading.Thread(target=cleanup, name='real-analysis-close', daemon=True).start()

    def submit_auto(self, payload, lesson_key, valid):
        from .auto_review import review_and_analyze
        key=('auto',lesson_key,payload['instance_key'],hashlib.sha256(payload['image']).hexdigest())
        if self.closing:raise ValueError('分析服务正在退出')
        if key in self.requests:return self.requests[key]
        if any(not f.done() for f in self.requests.values()):raise ValueError('已有 AI 请求进行中')
        future=self.service.pool.submit(review_and_analyze,self.service,dict(payload),lesson_key,valid)
        self.requests[key]=future
        return future
