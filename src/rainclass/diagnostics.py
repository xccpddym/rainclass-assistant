"""Read-only, aggregate-only diagnostics. No DOM text, URLs, headers or values."""
import json, time, argparse
from pathlib import Path

STATES = {"STOPPED", "RECOVERING", "IDLE_NO_CLASS", "IGNORE_PPT", "UNCERTAIN", "INCOMPLETE", "VERIFIED_QUESTION", "NEEDS_MANUAL", "DUPLICATE", "NOT_VERIFIED"}
SCRIPT = """() => {
const visible = e => !!(e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden');
const count = s => Array.from(document.querySelectorAll(s)).filter(visible).length;
return {visible_elements: count('body *'), buttons: count('button'), radios: count('input[type=radio]'), checkboxes: count('input[type=checkbox]'), text_fields: count('input:not([type=password]):not([type=hidden]),textarea'), frames: count('iframe'), revision: window.__rainRevision || 0};
}"""
class Diagnostics:
    def __init__(self, path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.last=None
    def record(self, structure, course_state="NOT_VERIFIED", detection="NOT_VERIFIED"):
        # Allowlist reconstruction: no arbitrary caller fields are serialized.
        metrics={k:min(10000000,max(0,int(structure.get(k,0)))) for k in ("visible_elements","buttons","radios","checkboxes","text_fields","frames","revision")}
        row={"structure":metrics,"course_state":course_state if course_state in STATES else "NOT_VERIFIED","detection":detection if detection in STATES else "NOT_VERIFIED"}
        if row==self.last:return
        self.last=row
        with self.path.open("a",encoding="utf-8") as f:f.write(json.dumps({"time_unix":time.time(),**row})+"\n")
    def sample(self,page,**kwargs): self.record(page.evaluate(SCRIPT),**kwargs)

def main():
    p=argparse.ArgumentParser(description="Read-only aggregate diagnostics; real platform semantics remain NOT_VERIFIED")
    p.add_argument('--url',required=True);p.add_argument('--allow-host',required=True)
    p.add_argument('--output',default='reports/readonly-diagnostics.jsonl');p.add_argument('--seconds',type=int,default=120)
    p.add_argument('--profile',default='.local/rainclass-edge-profile');args=p.parse_args()
    from urllib.parse import urlparse
    from .browser import Browser
    u=urlparse(args.url)
    if u.scheme!='https' or u.hostname!=args.allow_host or u.username or u.password: p.error('HTTPS exact allowed host required')
    b=Browser(args.profile,headless=False);d=Diagnostics(args.output)
    try:
        page=b.open(args.url);end=time.monotonic()+min(max(args.seconds,1),3600)
        while time.monotonic()<end:
            # Stop recording on SSO/external navigation; login is entirely manual.
            if urlparse(page.url).hostname==args.allow_host:d.sample(page)
            page.wait_for_timeout(1000)
    finally:b.close()
if __name__=='__main__':main()
