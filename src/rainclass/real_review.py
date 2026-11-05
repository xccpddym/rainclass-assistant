"""Human-reviewed local drafts; deliberately has no AI or submission dependency."""
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

KINDS={'single','multiple','blank','essay'}

@dataclass(frozen=True)
class ReviewedDraft:
    instance_key:str
    image_revision:str
    kind:str
    stem:str
    options:tuple
    blank_count:int

def validate_draft(instance_key, revision, kind, stem, options, blank_count):
    if not instance_key or not revision:raise ValueError('请先取得当前题目的原图')
    if kind not in KINDS:raise ValueError('请确认题型')
    stem=stem.strip()
    if not stem:raise ValueError('请填写并核对题干')
    if len(stem)>20000:raise ValueError('题干过长，请检查内容')
    lines=tuple(line.strip() for line in options.splitlines() if line.strip())
    if kind in ('single','multiple'):
        if not 2<=len(lines)<=26:raise ValueError('选择题须有 2–26 个选项，每行一个')
        lines=tuple(re.sub(r'^[A-Z][.、．:：]\s*','',line) for line in lines)
        if not all(lines):raise ValueError('选项内容不能为空')
    else:lines=()
    if kind=='blank' and (type(blank_count) is not int or not 1<=blank_count<=50):
        raise ValueError('请确认填空数量（1–50）')
    return ReviewedDraft(instance_key,revision,kind,stem,lines,blank_count if kind=='blank' else 0)

def load_seen(path):
    try:
        items=json.loads(Path(path).read_text(encoding='utf-8'))
        if not isinstance(items,list):return set()
        return {s for s in items[:10000] if isinstance(s,str) and re.fullmatch('[0-9a-f]{64}',s)}
    except (OSError,ValueError):return set()

def save_seen(path,items):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(sorted(items)),encoding='utf-8');temp.replace(path)

def ocr_bytes(image):
    import tempfile
    from .ocr import recognize
    with tempfile.TemporaryDirectory(prefix='rainclass-review-') as folder:
        path=Path(folder)/'question.png';path.write_bytes(image)
        return recognize(path)['text']

def type_hint(text):
    # A hint only; the user must confirm the editable type field.
    header=re.sub(r'\s+','',text[:80])
    found=[kind for label,kind in [('单选题','single'),('多选题','multiple'),('填空题','blank'),('主观题','essay'),('简答题','essay')] if label in header]
    return found[0] if len(set(found))==1 else 'UNKNOWN'
