from concurrent.futures import Future
from queue import Queue
from types import SimpleNamespace
import time
import pytest
from PySide6.QtWidgets import QApplication
from rainclass.real_panel import RealPanel
from rainclass.real_review import validate_draft
from rainclass.ai import validate,AnalysisError
from rainclass.real_analysis import question

@pytest.fixture
def panel(tmp_path):
    app=QApplication.instance() or QApplication([]);p=RealPanel(tmp_path,tmp_path/'rainclass-edge-profile')
    p.kind.setCurrentIndex(p.kind.findData('essay'));p.stem.setPlainText('说明原因')
    p.payload=dict(instance_key='essay',revision='r1',image=b'\x89PNG-test',ocr_pending=False,question_type='essay',option_count=0)
    p.active_key='essay';p.lesson_key='lesson';p.last_active_at=time.monotonic();p.dirty=False
    d=validate_draft('essay','r1','essay','说明原因','',0)
    result=dict(type='essay',stem=d.stem,suggested_answer=['完整答案。'],explanation='依据',uncertainty='请审查')
    calls=[]
    def submit(*args):
        calls.append(args);f=Future();f.set_result(result);return f
    def submit_auto(*args):
        calls.append(args);f=Future();f.set_result((d,result));return f
    p.analysis=SimpleNamespace(requests={},service=SimpleNamespace(persist=True),submit=submit,submit_auto=submit_auto,closing=False,store=SimpleNamespace(summary=lambda:[],history=lambda:[]))
    p.worker=SimpleNamespace(isRunning=lambda:True,answer_queue=Queue())
    yield p,calls
    p.worker=None;p.ai_timer.stop();p.deleteLater();app.processEvents()

def test_review_policy_blocks_global_auto_and_direct_analysis(panel):
    p,calls=panel;p.ai_enabled.setChecked(True);p.run_mode.setCurrentIndex(1)
    p.poll_auto();p.confirm();p.analyze_current()
    assert not calls and p.worker.answer_queue.empty()
    p.allow_essay();p.poll_analysis()
    assert len(calls)==1 and p.worker.answer_queue.get()[3] is True


def test_deny_cancels_and_survives_new_revision(panel):
    p,calls=panel;p.confirm();p.allow_essay();token=p.answer_valid;p.deny_essay()
    assert not token.is_set()
    p.poll_analysis();assert p.worker.answer_queue.empty()
    p.payload['revision']='r2';p.essay_mode.setCurrentIndex(1);p.poll_auto()
    assert len(calls)==1

@pytest.mark.parametrize('submit',[False,True])
def test_essay_auto_policy_independent_of_objective_mode(panel,submit):
    p,calls=panel;p.ai_enabled.setChecked(True);p.essay_mode.setCurrentIndex(1);p.essay_auto_submit.setChecked(submit)
    p.poll_auto();p.poll_auto()
    assert len(calls)==1
    command=p.worker.answer_queue.get();assert command[0].kind=='essay' and command[3] is submit


def test_essay_answer_must_be_single_string():
    d=validate_draft('i','r','essay','题干','',0);q=question(d,'lesson')
    for answer in ([],['a','b'],['x'*1001],['😀'*501]):
        with pytest.raises(AnalysisError):validate(q,dict(suggested_answer=answer,explanation='x',uncertainty='x'))


def test_essay_review_analysis_pipeline_and_budget(tmp_path):
    from rainclass.analysis import AnalysisService
    from rainclass.storage import Store
    from rainclass.auto_review import review_and_analyze
    from threading import Event
    class Client:
        remote=True;model_id='essay-test';profile={'max_request_cost':.1}
        def complete(self,messages,max_tokens=4096):return dict(readable=True,kind='essay',stem='说明原因',options=[],blank_count=0,warnings=[]),{}
        def analyze(self,q):
            assert q.kind=='essay'
            return dict(suggested_answer=['完整回答。'],explanation='依据',uncertainty='请审查'),{}
    store=Store(tmp_path/'db');service=AnalysisService(store,[Client()]);v=Event();v.set()
    try:
        d,r=review_and_analyze(service,dict(instance_key='i',revision='r',image=b'\x89PNG-test',question_type='essay',ocr_text='说明原因'), 'lesson',v)
        assert d.kind=='essay' and len(r['suggested_answer'])==1
        assert sum(x['requests'] for x in store.summary())==2
    finally:service.close();store.close()
