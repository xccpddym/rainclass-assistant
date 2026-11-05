import time
from rainclass.mock import Server
from rainclass.browser import Browser, MockAdapter, YuketangAdapter
from rainclass.core import Monitor

def wait(page,predicate):
 deadline=time.monotonic()+8
 while time.monotonic()<deadline:
  s=page.evaluate('window.classroomState')
  if s and predicate(s):return s
  page.wait_for_timeout(50)
 raise AssertionError('DOM snapshot timeout')

def test_edge_dom_end_to_end(tmp_path):
 server=Server().start();b=Browser(tmp_path/'rainclass-edge-profile');m=Monitor()
 try:
  page=b.open(server.url+'/student');a=MockAdapter(server.url)
  server.classroom.update({'action':'start'})
  wait(page,lambda s:s.get('course_active'))
  for i in range(50):
   server.classroom.update({'action':'ppt'})
   wait(page,lambda s:s.get('slide')==i+1)
   assert page.locator('#slide').inner_text().find('A/B/C/D')>=0
   assert m.observe(a.snapshot(page))[1] is None
  assert m.api_requests==0 and len(m.events)==0
  server.classroom.update({'action':'publish','id':'one'})
  wait(page,lambda s:(s.get('question') or {}).get('id')=='one')
  assert page.locator('[data-formal="exercise"] input').count()==3
  assert m.observe(a.snapshot(page))[1]
  page.reload();wait(page,lambda s:(s.get('question') or {}).get('id')=='one')
  assert m.observe(a.snapshot(page))[0]=='DUPLICATE'
  server.classroom.update({'action':'online','value':False})
  wait(page,lambda s:s.get('online') is False)
  assert m.observe(a.snapshot(page))[0]=='RECOVERING'
  server.classroom.update({'action':'online','value':True})
  wait(page,lambda s:s.get('online') is True)
  assert m.observe(a.snapshot(page))[0]=='DUPLICATE'
  assert page.evaluate('window.__rainRevision')>0
 finally:b.close();server.close()

def test_real_adapter_fails_closed():
 import pytest
 with pytest.raises(NotImplementedError):YuketangAdapter().snapshot(None)
