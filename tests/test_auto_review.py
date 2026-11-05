import json,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Event
import pytest
from rainclass.real_analysis import RealAnalysis

@pytest.fixture
def scene(tmp_path,monkeypatch):
    calls=[];control={'readable':True};valid=Event();valid.set()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append(body)
            review=isinstance(body['messages'][1]['content'],list)
            result=dict(readable=control['readable'],kind='single',stem='corrected',options=['4','5','6'],blank_count=0,warnings=[]) if review else dict(suggested_answer=['B'],explanation='2+3=5',uncertainty='verify')
            if review and control.get('cancel'):valid.clear()
            self.send_response(200);self.end_headers();self.wfile.write(json.dumps({'choices':[{'message':{'content':json.dumps(result)}}],'usage':{'prompt_tokens':5,'completion_tokens':5}}).encode())
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    monkeypatch.setenv('AUTO_TEST_KEY','local')
    config=dict(call_limit=10,budget=1,profiles=[dict(base_url=f'http://127.0.0.1:{server.server_port}',model='local',key_env='AUTO_TEST_KEY')])
    p=dict(instance_key='one',revision='r1',image=b'\x89PNG-test',ocr_text='ocr',option_count=3,question_type='UNKNOWN',ocr_pending=False)
    a=RealAnalysis(tmp_path/'db',config)
    yield a,p,valid,calls,control
    a.close();assert a.closed.wait(5);server.shutdown();server.server_close()

def test_vision_then_analysis_and_dedup(scene):
    a,p,v,calls,_=scene;f=a.submit_auto(p,'lesson',v);d,r=f.result(5)
    assert d.stem=='corrected' and r['suggested_answer']==['B']
    assert a.submit_auto({**p,'revision':'new'},'lesson',v) is f
    assert len(calls)==2 and calls[0]['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/png;base64,')
    assert sum(r['requests'] for r in a.store.summary())==2

@pytest.mark.parametrize('condition',['unreadable','cancel','budget'])
def test_failed_review_never_analyzes(scene,condition):
    a,p,v,calls,control=scene
    if condition=='unreadable':control['readable']=False
    elif condition=='cancel':control['cancel']=True
    else:a.service.budget=.1
    with pytest.raises(Exception):a.submit_auto(p,'lesson',v).result(5)
    assert len(calls)==1 and len(a.store.history())==0


def test_vision_and_analysis_have_no_request_count_cap(scene):
    from types import SimpleNamespace
    a,p,v,calls,_=scene
    for _ in range(20):a.store.record(SimpleNamespace(course_id='real-lesson:lesson'),'local','OK',{},1,{'max_request_cost':.1})
    a.set_budget(None)
    d,r=a.submit_auto(p,'lesson',v).result(5)
    assert len(calls)==2 and r['suggested_answer']==['B']
    assert a.service.call_limit is None
    assert sum(row['requests'] for row in a.store.summary())==22


def test_auto_ui_queues_once_and_edit_cancels(scene,tmp_path):
    from PySide6.QtWidgets import QApplication
    from types import SimpleNamespace
    from queue import Queue
    from rainclass.real_panel import RealPanel
    import time
    a,p,v,calls,control=scene
    app=QApplication.instance() or QApplication([]);panel=RealPanel(tmp_path,tmp_path/'rainclass-edge-profile')
    panel.analysis=a;panel.payload=p;panel.active_key='one';panel.lesson_key='lesson';panel.last_active_at=time.monotonic()
    panel.worker=SimpleNamespace(isRunning=lambda:True,answer_queue=Queue())
    panel.run_mode.setCurrentIndex(1);panel.ai_enabled.setChecked(True)
    panel.poll_auto();future=panel.auto_future;future.result(5);panel.poll_auto()
    assert panel.review_status=='AI_REVIEWED' and panel.worker.answer_queue.qsize()==1
    panel.poll_auto();assert len(calls)==2
    token=panel.worker.answer_queue.get()[2];assert token.is_set()
    panel.edited();assert not token.is_set()
    panel.worker=None;panel.ai_timer.stop();panel.deleteLater();app.processEvents()
