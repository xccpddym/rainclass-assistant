"""Loopback-only classroom fixture; no external platform endpoints."""
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from threading import Thread, Lock
from pathlib import Path
import json, time, uuid
from .core import detect
from .ai import validate, AnalysisError

class Classroom:
    def __init__(self):
        self.lock = Lock()
        self.state = dict(course_active=False, course_id="mock-1", online=True, slide=0, question=None, round=0, revision=0)
        self.delay_ms = 0
        self.receipts=[]
    def update(self, data):
        with self.lock:
            action = data.get("action")
            if action == "start": self.state.update(course_active=True, question=None)
            elif action == "end": self.state.update(course_active=False, question=None)
            elif action == "ppt": self.state.update(slide=self.state["slide"]+1, question=None)
            elif action == "online": self.state["online"] = bool(data["value"])
            elif action == "delay": self.delay_ms = min(5000, max(0, int(data["ms"])))
            elif action == "close" and self.state["question"]: self.state["question"]["closed"] = True
            elif action == "extend" and self.state["question"]: self.state["question"]["deadline"] = time.time()+float(data["seconds"])
            elif action == "publish":
                self.state["round"] += 1
                kind = data.get("type", "single")
                self.state["question"] = dict(id=data.get("id") or str(uuid.uuid4()), formal=True, same_container=True,
                    type=kind, controls=kind, stem=data.get("stem", "示例：2 + 2 = ___；3 + 3 = ___" if kind=="blank" else "示例：2 + 2 = ?"), options=data.get("options", [] if kind=="blank" else ["3", "4", "5"]),
                    blank_count=data.get("blank_count", 2) if kind=="blank" else 0, complete=data.get("complete", True),
                    published_at=time.time(), deadline=time.time()+data.get("seconds", 60))
            elif action == "complete" and self.state["question"]: self.state["question"]["complete"] = True
            self.state["revision"] += 1
    def submit(self, data):
        with self.lock:
            q=self.state.get('question') or {}
            if not self.state['online'] or not self.state['course_active'] or q.get('id')!=data.get('instance_id') or q.get('submitted') or q.get('closed') or time.time()>=q.get('deadline',0):
                raise ValueError('Question unavailable')
            status,question=detect(self.state)
            if question is None:raise ValueError('Unsupported question')
            validate(question,dict(suggested_answer=data.get('answers'),explanation='模拟提交',uncertainty='仅测试'))
            receipt={'instance_id':q['id'],'answers':data['answers'],'received_at':time.time(),'environment':'MOCK_ONLY'}
            q.update(submitted=True,receipt=receipt);self.receipts.append(receipt);self.state['revision']+=1
            return receipt
    def snapshot(self):
        with self.lock: return {**json.loads(json.dumps(self.state)), 'observed_at':time.time()}

class Server:
    def __init__(self, port=0):
        self.classroom = Classroom()
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                if self.path == "/state":
                    time.sleep(owner.classroom.delay_ms/1000)
                    s=owner.classroom.snapshot()
                    if not s["online"]: self.send_error(503); return
                    body=json.dumps(s).encode(); content="application/json"
                elif self.path in ("/", "/teacher", "/student"):
                    body=(Path(__file__).parent/"mock.html").read_bytes(); content="text/html; charset=utf-8"
                else: self.send_error(404); return
                self.send_response(200); self.send_header("Content-Type", content); self.end_headers(); self.wfile.write(body)
            def do_POST(self):
                if self.path == '/submit':
                    try:
                        data=json.loads(self.rfile.read(min(int(self.headers.get('Content-Length',0)),65536)))
                        receipt=owner.classroom.submit(data)
                        self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps(receipt).encode())
                    except (ValueError,KeyError,TypeError,AnalysisError):self.send_error(409)
                    return
                if self.path != "/control": self.send_error(404); return
                try:
                    owner.classroom.update(json.loads(self.rfile.read(min(int(self.headers.get("Content-Length",0)),65536))))
                    self.send_response(204); self.end_headers()
                except (ValueError, KeyError, TypeError): self.send_error(400)
        self.http = ThreadingHTTPServer(("127.0.0.1",port), Handler)
        self.url = f"http://127.0.0.1:{self.http.server_port}"
    def start(self):
        Thread(target=self.http.serve_forever, daemon=True).start()
        return self
    def close(self): self.http.shutdown(); self.http.server_close()

if __name__ == "__main__":
    server=Server(8765).start()
    print(server.url+"/teacher", flush=True)
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt: server.close()
