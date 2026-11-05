import json,time,math
from pathlib import Path
from rainclass.mock import Server
from rainclass.browser import Browser,MockAdapter
from rainclass.core import Monitor
from rainclass.diagnostics import Diagnostics

def test_round_one(tmp_path):
 server=Server().start();b=Browser(tmp_path/'rainclass-edge-profile');m=Monitor();rows=[];latencies=[]
 started=time.monotonic()
 def observe_until(page,predicate):
  end=time.monotonic()+10
  while time.monotonic()<end:
   s=page.evaluate('window.classroomState') or {}
   if predicate(s):return m.observe(s)
   page.wait_for_timeout(40)
  raise AssertionError('snapshot not received')
 def control(teacher,data):
  teacher.evaluate("async d => {await fetch('/control',{method:'POST',body:JSON.stringify(d)})}",data)
 try:
  student=b.open(server.url+'/student');teacher=b.context.new_page();teacher.goto(server.url+'/teacher')
  teacher.get_by_role('button',name='开始课程',exact=True).click()
  observe_until(student,lambda s:s.get('course_active'))
  for i in range(50):
   teacher.get_by_role('button',name='下一页 PPT（含 A/B/C/D）',exact=True).click()
   state,q=observe_until(student,lambda s:s.get('slide')==i+1)
   rows.append({'case':'ppt','passed':q is None and state=='IGNORE_PPT'})
  false_positives=len(m.events)+len(m.manual_events)
  for kind in ['single','multiple','blank','essay']:
   for i in range(20):
    ident=f'{kind}-{i}';t=time.monotonic();control(teacher,{'action':'publish','type':kind,'id':ident})
    state,q=observe_until(student,lambda s:(s.get('question') or {}).get('id')==ident)
    latencies.append(time.monotonic()-t)
    rows.append({'case':kind,'passed':state==('NEEDS_MANUAL' if kind=='essay' else 'VERIFIED_QUESTION') and (q is None if kind=='essay' else q.kind==kind)})
    for repeat in range(3):assert m.observe(MockAdapter(server.url).snapshot(student))[0]=='DUPLICATE'
  before=len(m.events)+len(m.manual_events)
  student.reload();observe_until(student,lambda s:(s.get('question') or {}).get('id')=='essay-19')
  rows.append({'case':'reload_dedup','passed':len(m.events)+len(m.manual_events)==before})
  control(teacher,{'action':'delay','ms':1200});t=time.monotonic()
  control(teacher,{'action':'publish','type':'single','id':'delayed'})
  state,q=observe_until(student,lambda s:(s.get('question') or {}).get('id')=='delayed')
  delay=time.monotonic()-t;rows.append({'case':'delay_1200ms','passed':q is not None})
  control(teacher,{'action':'delay','ms':0})
  control(teacher,{'action':'online','value':False});observe_until(student,lambda s:s.get('online') is False)
  student.wait_for_timeout(5000);t=time.monotonic()
  control(teacher,{'action':'online','value':True});state,q=observe_until(student,lambda s:s.get('online') is True)
  recovery=time.monotonic()-t;rows.append({'case':'reconnect_dedup','passed':state=='DUPLICATE'})
  control(teacher,{'action':'publish','type':'blank','id':'after-recovery'})
  state,q=observe_until(student,lambda s:(s.get('question') or {}).get('id')=='after-recovery')
  rows.append({'case':'new_after_recovery','passed':q is not None})
  d=Diagnostics(tmp_path/'diag.jsonl');d.sample(student,detection=state)
  assert 'stem' not in (tmp_path/'diag.jsonl').read_text()
  times=sorted(latencies)
  report={'cases':rows,'passed':sum(x['passed'] for x in rows),'total':len(rows),'false_positive_events':false_positives,'missed_questions':sum(not x['passed'] for x in rows if x['case'] in ['single','multiple','blank','essay']),'duplicate_events':len(m.events)+len(m.manual_events)-82,'supported_events':len(m.events),'manual_events':len(m.manual_events),'api_requests':m.api_requests,'seconds':time.monotonic()-started,'publish_to_detection_seconds':{'p50':times[math.ceil(len(times)*.5)-1],'p95':times[math.ceil(len(times)*.95)-1],'p99':times[math.ceil(len(times)*.99)-1],'max':max(times)},'delayed_detection_seconds':delay,'reconnect_detection_seconds':recovery}
  out=Path(__file__).resolve().parents[1]/'reports';out.mkdir(exist_ok=True)
  (out/'round1.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
  assert all(x['passed'] for x in rows)
  assert report['false_positive_events']==report['missed_questions']==report['duplicate_events']==0
 finally:b.close();server.close()

def test_diagnostics_allowlist(tmp_path):
 p=tmp_path/'safe.jsonl';d=Diagnostics(p)
 d.record({'buttons':2,'cookie':'SECRET','url':'?token=SECRET','html':'SECRET'},course_state='SECRET',detection='SECRET')
 data=p.read_text();assert 'SECRET' not in data and 'cookie' not in data and 'url' not in data
 assert json.loads(data)['detection']=='NOT_VERIFIED'
