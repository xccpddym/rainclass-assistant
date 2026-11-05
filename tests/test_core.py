import pytest
from rainclass.core import Monitor, detect, Countdown
from rainclass.mock import Classroom

@pytest.mark.parametrize('kind',['single','multiple','blank','essay','unknown'])
@pytest.mark.parametrize('case',range(20))
def test_types(kind,case):
 c=Classroom();c.update({'action':'start'});c.update({'action':'publish','type':kind})
 state,q=detect(c.snapshot())
 assert state==('VERIFIED_QUESTION' if kind in ['single','multiple','blank'] else 'NEEDS_MANUAL')
 if q: assert q.kind==kind

def test_fifty_slides_zero_requests():
 c=Classroom();c.update({'action':'start'});m=Monitor()
 for i in range(50):
  c.update({'action':'ppt'});s=c.snapshot();s['text']='问题 A/B/C/D 提交 倒计时'
  assert m.observe(s)[1] is None
 assert len(m.events)==m.api_requests==0

def test_incomplete_duplicate_recovery_and_new_instance():
 c=Classroom();c.update({'action':'start'});m=Monitor()
 c.update({'action':'publish','complete':False});assert m.observe(c.snapshot())[0]=='INCOMPLETE'
 c.update({'action':'complete'});assert m.observe(c.snapshot())[1]
 for i in range(20):assert m.observe(c.snapshot())[0]=='DUPLICATE'
 c.update({'action':'online','value':False});assert m.observe(c.snapshot())[0]=='RECOVERING'
 c.update({'action':'online','value':True});assert m.observe(c.snapshot())[0]=='DUPLICATE'
 c.update({'action':'publish'});assert m.observe(c.snapshot())[1]
 assert m.events[0].fingerprint==m.events[1].fingerprint
 c.update({'action':'end'});assert m.observe(c.snapshot())[0]=='IDLE_NO_CLASS'

@pytest.mark.parametrize('field,value',[('formal',False),('same_container',False),('submitted',True),('closed',True),('stem',''),('images',['x']),('controls','bad')])
def test_reject_unsafe(field,value):
 c=Classroom();c.update({'action':'start'});c.update({'action':'publish'})
 s=c.snapshot();s['question'][field]=value;assert detect(s)[1] is None

def test_countdown():
 c=Countdown();assert c.remaining() is None
 c.sync(10);assert 9<c.remaining()<=10
 c.sync(20);assert 19<c.remaining()<=20
 c.sync(None);assert c.remaining() is None
