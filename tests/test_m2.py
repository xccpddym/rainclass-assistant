import json,threading,time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import pytest
from rainclass.ai import FakeAI,CompatibleAI,validate,AnalysisError,Retryable
from rainclass.storage import Store
from rainclass.analysis import AnalysisService
from rainclass.core import detect
from rainclass.mock import Classroom

@pytest.fixture
def question():
 c=Classroom();c.update({'action':'start'});c.update({'action':'publish'})
 return detect(c.snapshot())[1]

@pytest.fixture
def store(tmp_path):
 s=Store(tmp_path/'db.sqlite');yield s;s.close()

@pytest.mark.parametrize('kind',['single','multiple','blank'])
def test_fake_schema(question,kind):
 q=replace(question,kind=kind,blank_count=2);d,u=FakeAI().analyze(q)
 assert validate(q,d)['uncertainty'];assert u=={}

def test_cache_reopen_and_dedup(question,tmp_path):
 path=tmp_path/'db';s=Store(path);a=AnalysisService(s)
 f=a.submit(question);assert a.submit(question) is f
 assert f.result()['cache_status']=='MISS';a.close();s.close()
 s=Store(path);a=AnalysisService(s)
 try:
  result=a.submit(replace(question,instance_id='new')).result()
  assert result['cache_status']=='HIT' and result['historical'] and result['question_instance_id']=='new'
  assert s.summary()==[]
  s.clear();assert s.history()==[]
 finally:a.close();s.close()

@pytest.mark.parametrize('answer',[['Z'],['A','A'],[],['A','B']])
def test_bad_single_schema(question,answer):
 with pytest.raises(AnalysisError):validate(question,dict(suggested_answer=answer,explanation='x',uncertainty='x'))

def test_no_persistence(question,store):
 a=AnalysisService(store,persist=False)
 try:
  assert a.submit(question).result()['cache_status']=='MISS'
  assert store.history()==[]
 finally:a.close()

class Reject:
 remote=True;model_id='reject';profile={'max_request_cost':.1}
 def __init__(self):self.calls=0
 def analyze(self,q):self.calls+=1;raise Retryable('503')

def test_retry_fallback_and_accounting(question,store):
 bad=Reject();a=AnalysisService(store,[bad,FakeAI()])
 try:
  assert a.submit(question).result()['status']=='DEMO'
  assert bad.calls==2
  assert store.summary()[0]['requests']==2
 finally:a.close()

def test_budget_stops_retry(question,store):
 bad=Reject();a=AnalysisService(store,[bad],budget=.1)
 try:
  with pytest.raises(AnalysisError,match='budget'):a.submit(question).result()
  assert bad.calls==1
 finally:a.close()

def test_unknown_outcome_not_retried(question,store):
 class Unknown(Reject):
  def analyze(self,q):self.calls+=1;raise AnalysisError('outcome unknown')
 bad=Unknown();a=AnalysisService(store,[bad,FakeAI()])
 try:
  with pytest.raises(AnalysisError):a.submit(question).result()
  assert bad.calls==1
 finally:a.close()

def test_real_client_local_http(question,store,monkeypatch):
 seen=[]
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def do_POST(self):
   data=json.loads(self.rfile.read(int(self.headers['Content-Length'])));seen.append(data)
   self.send_response(200);self.end_headers()
   self.wfile.write(json.dumps({'choices':[{'message':{'content':json.dumps({'suggested_answer':['B'],'explanation':'local mock','uncertainty':'not guaranteed'})}}],'usage':{'prompt_tokens':10,'completion_tokens':5}}).encode())
 srv=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=srv.serve_forever,daemon=True).start()
 monkeypatch.setenv('TEST_MODEL_KEY','test-only')
 profile=dict(base_url=f'http://127.0.0.1:{srv.server_port}/v1',model='test',key_env='TEST_MODEL_KEY',input_price=1,output_price=2,max_request_cost=.1)
 a=AnalysisService(store,[CompatibleAI(profile)])
 try:
  result=a.submit(question).result()
  assert result['suggested_answer']==['B'] and result['source_model']=='test'
  row=store.summary()[0]
  assert row['cache_hit_tokens'] is None and row['cache_miss_tokens'] is None
  assert row['estimated_cost']==pytest.approx(.00002)
  assert seen[0]['messages'][0]['role']=='system'
 finally:a.close();srv.shutdown();srv.server_close()

def test_missing_key_never_contacts_provider(question,monkeypatch):
 monkeypatch.delenv('UNSET_TEST_KEY',raising=False)
 c=CompatibleAI(dict(base_url='http://127.0.0.1:1/v1',model='test',key_env='UNSET_TEST_KEY'))
 with pytest.raises(AnalysisError,match='unset'):c.analyze(question)

def test_decimal_step_budget_does_not_block_due_to_float_rounding(question,store):
 for _ in range(3):
  assert store.allowance(question.course_id,20,.3,.1)
  store.record(question,'budget-test','OK',{},1,{'max_request_cost':.1})
 assert not store.allowance(question.course_id,20,.3,.1)
