from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib,json,time,threading
from .ai import FakeAI,CompatibleAI,validate,AnalysisError,Retryable,PROMPT_VERSION

class AnalysisService:
 def __init__(self,store,clients=None,persist=True,call_limit=20,budget=1.0):
  self.store=store;self.clients=clients or [FakeAI()];self.persist=persist
  self.call_limit=call_limit;self.budget=budget;self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='rainclass-analysis');self.pending={};self.lock=threading.Lock()
 def submit(self,q,force=False):
  key=(q.course_id,q.instance_id)
  with self.lock:
   if key in self.pending and not force:return self.pending[key]
   # Never overlap forced analysis with a running request.
   if key in self.pending and not self.pending[key].done():return self.pending[key]
   f=self.pool.submit(self.analyze,q,force);self.pending[key]=f;return f
 def analyze(self,q,force=False):
  if q.kind not in ('single','multiple','blank','essay'):raise AnalysisError('Manual handling required')
  for index,client in enumerate(self.clients[:2]):
   cache_key=hashlib.sha256(json.dumps([q.fingerprint,client.model_id,getattr(client,'profile',{}).get('base_url','fake'),PROMPT_VERSION]).encode()).hexdigest()
   old=self.store.cached(cache_key) if not force and self.persist else None
   if old:
    validate(q,old)
    result={**old,'question_instance_id':q.instance_id,'cache_status':'HIT','historical':True}
    self.store.save(cache_key,q,result,self.persist);return result
   profile=getattr(client,'profile',{})
   for attempt in range(2):
    reserve=float(profile.get('max_request_cost',0.1))
    if client.remote and (reserve<=0 or not self.store.allowance(q.course_id,self.call_limit,self.budget,reserve)):raise AnalysisError('Course budget reached' if self.call_limit is None else 'Course budget/call limit reached')
    start=time.monotonic()
    try:
     data,usage=client.analyze(q);data=validate(q,data)
    except AnalysisError as e:
     if client.remote:self.store.record(q,client.model_id,'FAILED',{},(time.monotonic()-start)*1000,profile)
     if isinstance(e,Retryable):
      if attempt==0:time.sleep(.25);continue
      if index+1<len(self.clients[:2]):break
     raise
    else:
     duration=(time.monotonic()-start)*1000
     if client.remote:self.store.record(q,client.model_id,'OK',usage,duration,profile)
     result={**data,'question_instance_id':q.instance_id,'type':q.kind,'stem':q.stem,'options':list(q.options),'source_model':client.model_id,'prompt_version':PROMPT_VERSION,'duration_ms':duration,'token_usage':usage,'cache_status':'MISS','status':'DEMO' if not client.remote else 'RESULT_READY','historical':False}
     # Persist only allowlisted token fields; no arbitrary provider data.
     result['token_usage']={k:v for k,v in usage.items() if k in ('prompt_tokens','completion_tokens','prompt_cache_hit_tokens','prompt_cache_miss_tokens') and isinstance(v,int) and not isinstance(v,bool) and v>=0}
     self.store.save(cache_key,q,result,self.persist);return result
  raise AnalysisError('No model result')
 def close(self):self.pool.shutdown(wait=True,cancel_futures=True)
