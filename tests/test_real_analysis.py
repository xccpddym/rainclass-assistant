import json, threading, time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import pytest
from rainclass.real_analysis import RealAnalysis,question
from rainclass.real_review import ReviewedDraft
from rainclass.ai import AnalysisError

@pytest.fixture
def endpoint(monkeypatch):
    calls=[];release=threading.Event();release.set()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            data=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append(data)
            release.wait(3)
            q=json.loads(data['messages'][1]['content'])
            answer=['A'] if q['kind']=='single' else ['A','B'] if q['kind']=='multiple' else ['x']*q['blank_count']
            self.send_response(200);self.end_headers()
            self.wfile.write(json.dumps({'choices':[{'message':{'content':json.dumps(dict(suggested_answer=answer,explanation='参考',uncertainty='请核对'))}}]}).encode())
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    monkeypatch.setenv('REAL_TEST_KEY','local-only')
    config=dict(call_limit=20,budget=1,profiles=[dict(base_url=f'http://127.0.0.1:{server.server_port}/v1',model='local',key_env='REAL_TEST_KEY')])
    yield config,calls,release
    release.set();server.shutdown();server.server_close()

def draft(kind='single'):
    return ReviewedDraft('instance','revision',kind,'题干',('one','two') if kind!='blank' else (),2 if kind=='blank' else 0)

def finish(a):
    a.close();assert a.closed.wait(4)

@pytest.mark.parametrize('kind',['single','multiple','blank'])
def test_bridge_http_dedup_cache_revision_and_edit(endpoint,tmp_path,kind):
    config,calls,release=endpoint;a=RealAnalysis(tmp_path/'db',config)
    try:
        d=draft(kind);f=a.submit(d,'lesson');r=f.result(3)
        assert a.submit(d,'lesson') is f
        assert a.submit(replace(d,image_revision='new'),'lesson') is f
        assert r['status']=='RESULT_READY' and len(calls)==1
        assert a.submit(replace(d,instance_key='other'),'lesson').result(3)['cache_status']=='HIT'
        assert len(calls)==1
        a.submit(replace(d,stem='修改题干'),'lesson').result(3)
        assert len(calls)==2
        assert sum(x['requests'] for x in a.store.summary())==2
    finally:finish(a)

def test_no_fake_missing_config_and_unsupported(endpoint,tmp_path,monkeypatch):
    config,calls,_=endpoint
    with pytest.raises(ValueError):RealAnalysis(tmp_path/'db',{})
    monkeypatch.delenv('REAL_TEST_KEY')
    with pytest.raises(ValueError):RealAnalysis(tmp_path/'db',config)
    with pytest.raises(ValueError):question(replace(draft(),kind='unsupported'),'lesson')
    with pytest.raises(ValueError):question(replace(draft(),options=('x'*60000,'y')),'lesson')
    assert calls==[]

def test_nonblocking_close_cancels_and_accounts(endpoint,tmp_path):
    config,calls,release=endpoint;release.clear();a=RealAnalysis(tmp_path/'db',config)
    f=a.submit(draft(),'lesson')
    deadline=time.monotonic()+2
    while not calls and time.monotonic()<deadline:time.sleep(.01)
    with pytest.raises(ValueError):a.submit(replace(draft(),stem='new'),'lesson')
    start=time.monotonic();a.close();assert time.monotonic()-start<.2
    release.set();assert a.closed.wait(4)


def test_ui_stale_result_cannot_replace_current(endpoint,tmp_path):
    from PySide6.QtWidgets import QApplication
    from rainclass.real_panel import RealPanel
    config,calls,release=endpoint;release.clear()
    app=QApplication.instance() or QApplication([]);p=RealPanel(tmp_path,tmp_path/'rainclass-edge-profile')
    p.ai_config=config;p.ai_enabled.setChecked(True)
    d=draft();p.active_key=d.instance_key;p.lesson_key='lesson';p.payload=dict(instance_key=d.instance_key,revision=d.image_revision)
    p.confirmed=d;p.review_status='REVIEWED';p.last_active_at=time.monotonic()
    p.analyze_current();f=p.analysis_future
    p.edited();release.set();f.result(3);p.poll_analysis()
    assert '建议答案' not in p.ai_output.toPlainText()
    assert p.analysis.store.history()
    p.close_analysis();assert p.analysis.closed.wait(3);p.hide();p.deleteLater();app.processEvents()

def test_budget_and_private_results(endpoint,tmp_path):
    config,calls,_=endpoint;config={**config,'budget':.1}
    a=RealAnalysis(tmp_path/'db',config,persist=False)
    try:
        a.submit(draft(),'lesson').result(3)
        assert a.store.history()==[]
        assert len(a.store.summary())==1
        d=replace(draft(),stem='new')
        f=a.submit(d,'lesson')
        with pytest.raises(AnalysisError):f.result(3)
        assert a.submit(d,'lesson') is f
        assert len(calls)==1
    finally:finish(a)


def test_budget_change_only_releases_budget_failures(endpoint,tmp_path):
    from concurrent.futures import Future
    config,calls,_=endpoint;a=RealAnalysis(tmp_path/'db',config)
    try:
        budget=Future();budget.set_exception(AnalysisError('单课预算或调用上限已达到'))
        unknown=Future();unknown.set_exception(AnalysisError('outcome unknown'))
        a.requests={('auto','lesson','instance','image'):budget,('auto','lesson','other','otherimage'):unknown}
        assert a.set_budget(.5)==[('instance','image')]
        assert list(a.requests.values())==[unknown]
        assert calls==[]
    finally:finish(a)


def test_real_analysis_ignores_legacy_count_cap_after_twenty_requests(endpoint,tmp_path):
    from rainclass.real_analysis import question
    config,calls,_=endpoint
    a=RealAnalysis(tmp_path/'db',{**config,'budget':None,'call_limit':2},persist=False)
    try:
        for _ in range(20):a.store.record(question(draft(),'lesson'),'local','OK',{},1,{'max_request_cost':.1})
        assert a.service.call_limit is None
        a.submit(draft(),'lesson').result(3)
        a.submit(replace(draft(),stem='second'),'lesson').result(3)
        a.submit(replace(draft(),stem='third'),'lesson').result(3)
        assert len(calls)==3
        a.set_budget(.1)
        assert not a.store.allowance('real-lesson:lesson',None,.1,.1)
        a.set_budget(None)
        assert a.store.allowance('real-lesson:lesson',None,None,100)
    finally:finish(a)
