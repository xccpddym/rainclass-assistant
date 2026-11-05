"""Pure detection rules; never infer a question from slide text."""
from dataclasses import dataclass
import hashlib, json, re, time

@dataclass(frozen=True)
class Question:
    instance_id: str
    course_id: str
    kind: str
    stem: str
    options: tuple
    blank_count: int
    fingerprint: str

def normalize(s):
    return re.sub(r"\s+", " ", str(s)).strip()

def detect(s):
    if not s.get("online", True): return "RECOVERING", None
    if not s.get("course_active"): return "IDLE_NO_CLASS", None
    q = s.get("question")
    if not q or q.get("closed") or q.get("submitted"): return "IGNORE_PPT", None
    if not q.get("formal") or not q.get("same_container"): return "UNCERTAIN", None
    kind, stem = q.get("type"), normalize(q.get("stem", ""))
    if not stem or not q.get("complete"): return "INCOMPLETE", None
    if kind not in ("single", "multiple", "blank"): return "NEEDS_MANUAL", None
    options = tuple(normalize(x) for x in q.get("options", []))
    blanks = q.get("blank_count", 0)
    if not stem or not q.get("complete") or q.get("images"):
        return "INCOMPLETE", None
    if kind in ("single", "multiple") and (len(options)<2 or not all(options) or q.get("controls") != kind):
        return "INCOMPLETE", None
    if kind == "blank" and (not isinstance(blanks, int) or blanks < 1 or q.get("controls") != "blank"):
        return "INCOMPLETE", None
    content = json.dumps([kind, stem, options, blanks], ensure_ascii=False)
    fp = hashlib.sha256(content.encode()).hexdigest()
    instance = str(q.get("id") or (str(s.get("round", "")) + ":" + fp))
    return "VERIFIED_QUESTION", Question(instance, str(s.get("course_id")), kind, stem, options, blanks, fp)

class Monitor:
    def __init__(self):
        self.seen = set()
        self.events = []
        self.manual_events = []
        self.api_requests = 0
        self.state = "STOPPED"
    def observe(self, snapshot):
        state, q = detect(snapshot)
        if q:
            key = (q.course_id, q.instance_id)
            if key in self.seen: state, q = "DUPLICATE", None
            else:
                self.seen.add(key)
                self.events.append(q)
        if state == "NEEDS_MANUAL":
            raw = snapshot.get("question") or {}
            key = (str(snapshot.get("course_id")), str(raw.get("id") or snapshot.get("round")))
            if key in self.seen: state = "DUPLICATE"
            else:
                self.seen.add(key)
                self.manual_events.append({"kind": str(raw.get("type", "unknown")), "stem": normalize(raw.get("stem", "")), "instance_id": key[1]})
        self.state = state
        return state, q

class Countdown:
    def __init__(self): self.deadline = None
    def sync(self, seconds):
        self.deadline = time.monotonic() + max(0, seconds) if seconds is not None else None
    def remaining(self):
        return None if self.deadline is None else max(0, self.deadline-time.monotonic())
