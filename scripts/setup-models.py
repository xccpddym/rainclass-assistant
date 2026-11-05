"""Install the three official RapidOCR model artifacts with hash verification."""
from pathlib import Path
import hashlib,urllib.request

ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT/'.local/ocr-runtime/rapidocr/models'
BASE='https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/'
MODELS={
    'PP-OCRv6_det_small.onnx':('PP-OCRv6/det/','090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f'),
    'PP-OCRv6_rec_small.onnx':('PP-OCRv6/rec/','6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884'),
    'ch_ppocr_mobile_v2.0_cls_mobile.onnx':('PP-OCRv4/cls/','e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c'),
}

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

if __name__=='__main__':
    assert (TARGET.parent/'__init__.py').exists(),'Run setup-ocr.ps1 first'
    TARGET.mkdir(parents=True,exist_ok=True)
    for name,(subdir,expected) in MODELS.items():
        path=TARGET/name
        if path.exists() and sha(path)==expected:print(name,'already verified');continue
        temp=path.with_suffix('.download')
        with urllib.request.urlopen(BASE+subdir+name,timeout=120) as response,temp.open('wb') as f:
            for chunk in iter(lambda:response.read(1024*1024),b''):f.write(chunk)
        if sha(temp)!=expected:temp.unlink();raise RuntimeError('Model SHA-256 mismatch: '+name)
        temp.replace(path);print(name,'verified')
