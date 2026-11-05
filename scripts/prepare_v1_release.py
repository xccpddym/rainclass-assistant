"""Prepare a portable release from build output; never copy personal runtime data."""
from pathlib import Path
from importlib.metadata import distributions,version
import hashlib,html,json,os,platform,shutil,subprocess,sys,zipfile

ROOT=Path(__file__).resolve().parents[1]
BUNDLE=ROOT/'dist/v1.0.0/RainClassAssistant'
RELEASE=ROOT/'release'

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def prepare():
    assert (BUNDLE/'RainClassAssistant.exe').is_file()
    assert not (BUNDLE/'_internal/icuuc.dll').exists(),'Private ICU conflict'
    # Only this checked-in, secret-free example is used as runnable config.
    for target in ('config.toml','config.example.toml'):
        shutil.copy2(ROOT/'config.example.toml',BUNDLE/target)
    guide=(ROOT/'使用说明.md').read_text(encoding='utf-8')
    (BUNDLE/'使用说明.md').write_text(guide,encoding='utf-8')
    (BUNDLE/'使用说明.txt').write_text(guide,encoding='utf-8-sig')
    blocks=[];paragraph=[];in_list=False
    def flush():
        if paragraph:blocks.append('<p>'+html.escape(' '.join(paragraph))+'</p>');paragraph.clear()
    for line in guide.splitlines():
        if not line.strip():
            flush()
            if in_list:blocks.append('</ul>');in_list=False
        elif line.startswith('#'):
            flush();n=len(line)-len(line.lstrip('#'));blocks.append(f'<h{n}>'+html.escape(line[n:].strip())+f'</h{n}>')
        elif line.startswith('- '):
            flush()
            if not in_list:blocks.append('<ul>');in_list=True
            blocks.append('<li>'+html.escape(line[2:])+'</li>')
        else:paragraph.append(line)
    flush()
    if in_list:blocks.append('</ul>')
    (BUNDLE/'使用说明.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RainClass 使用说明</title><style>body{font:16px/1.85 "Microsoft YaHei",sans-serif;color:#172b45;background:#f4f6fa;margin:0}article{max-width:900px;margin:30px auto;background:white;padding:36px;border:1px solid #dce2eb;border-radius:10px}h1,h2{line-height:1.4}h2{margin-top:32px;border-bottom:1px solid #dce2eb;padding-bottom:10px}li{margin:8px 0}p{overflow-wrap:anywhere}@media(max-width:700px){article{margin:0;padding:20px}}</style><article>'+''.join(blocks)+'</article></html>',encoding='utf-8')
    names={'pyside6','pyside6_addons','pyside6_essentials','shiboken6','playwright','greenlet','pyee','typing_extensions','pyinstaller','rapidocr','onnxruntime','numpy','opencv-python-headless','pyclipper','shapely','pyyaml','pillow','tqdm','omegaconf','antlr4-python3-runtime','requests','colorlog','six','coloredlogs','flatbuffers','protobuf','sympy','humanfriendly','packaging','certifi','charset-normalizer','idna','urllib3','pandas','lxml','fsspec','mpmath','pytz','python-dateutil','tzdata','psutil','filelock','cryptography','cffi','pycparser'}
    found={}
    for d in distributions(path=[str(ROOT/'.local/ocr-runtime'),*sys.path]):
        name=d.metadata.get('Name','')
        if name.lower() not in names or name.lower() in found:continue
        files=[]
        for item in d.files or []:
            if not any(t.lower() in ('licenses','license') for t in item.parts) and not item.name.lower().startswith(('license','copying','notice','copyright','model_licenses')):continue
            source=Path(d.locate_file(item))
            if not source.is_file():continue
            relative=Path(*[t for t in item.parts if t not in ('..','.')])
            target=BUNDLE/'THIRD_PARTY_LICENSES'/name/relative
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target);files.append(relative.as_posix())
        found[name.lower()]={'name':name,'version':d.version,'license_files':files}
    python_license=Path(sys.executable).parent/'LICENSE.txt'
    if python_license.exists():shutil.copy2(python_license,BUNDLE/'THIRD_PARTY_LICENSES/PYTHON_LICENSE.txt')
    models=[{'name':p.name,'sha256':digest(p)} for p in sorted((BUNDLE/'_internal/rapidocr/models').glob('*.onnx'))]
    assert len(models)==3,'Offline OCR models missing'
    (BUNDLE/'THIRD_PARTY_NOTICES.json').write_text(json.dumps({'dependencies':list(found.values()),'models':models,'model_notice':'THIRD_PARTY_LICENSES/rapidocr/rapidocr-3.10.0.dist-info/licenses/MODEL_LICENSES.md'},ensure_ascii=False,indent=2),encoding='utf-8')
    revision=subprocess.check_output(['git','-c',f'safe.directory={ROOT.as_posix()}','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    (BUNDLE/'BUILD_INFO.json').write_text(json.dumps({'version':'1.0.0','source_revision':revision,'python':platform.python_version(),'architecture':platform.machine(),'pyinstaller':version('pyinstaller'),'format':'portable-folder','real_classroom':'USER_ACCEPTED_ON_THIS_MACHINE','other_machines':'NOT_VERIFIED','signed':False},indent=2),encoding='utf-8')
    print(json.dumps({'bundle':str(BUNDLE),'models':len(models),'dependency_notices':len(found)},ensure_ascii=False))

def archive():
    evidence=ROOT/'.local/exe-release-check'
    for name in ('smoke.json','ocr.json'):
        result=json.loads((evidence/name).read_text(encoding='utf-8'))
        assert result['pass'] and result['frozen'] and result['cloud_requests']==0,name
    assert (BUNDLE/'config.toml').read_bytes()==(ROOT/'config.example.toml').read_bytes()
    forbidden={'.env','cookies','cookies.json','login data','web data','history'}
    key=os.environ.get('DEEPSEEK_API_KEY','').encode()
    count=0
    for p in BUNDLE.rglob('*'):
        if not p.is_file():continue
        assert p.name.lower() not in forbidden and 'rainclass-edge-profile' not in p.parts and not p.name.endswith(('.sqlite3','.sqlite3-wal','.jsonl')),p.name
        if len(key)>16:
            with p.open('rb') as f:
                previous=b''
                while chunk:=f.read(1024*1024):
                    assert key not in previous+chunk,'Secret detected in release'
                    previous=chunk[-len(key):]
        count+=1
    RELEASE.mkdir(exist_ok=True)
    target=Path(shutil.make_archive(str(RELEASE/'RainClassAssistant-1.0.0-win-x64'),'zip',BUNDLE.parent,BUNDLE.name))
    with zipfile.ZipFile(target) as z:assert z.testzip() is None
    sha=digest(target)
    (RELEASE/(target.name+'.sha256')).write_text(sha+'  '+target.name+'\n',encoding='ascii')
    print(json.dumps({'archive':str(target),'bytes':target.stat().st_size,'sha256':sha,'files':count,'secret_scan_passed':True},ensure_ascii=False))

if __name__=='__main__':
    if '--archive' in sys.argv:archive()
    else:prepare()
