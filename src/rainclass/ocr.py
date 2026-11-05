"""Optional Windows local OCR; never calls cloud services."""
import json,os,subprocess,re
from pathlib import Path

def recognize(image_path):
 image=Path(image_path).resolve()
 if not image.is_file():raise ValueError('Image file required')
 shell=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
 completed=subprocess.run([str(shell),'-NoProfile','-NonInteractive','-File',str(Path(__file__).with_name('ocr_windows.ps1')),'-ImagePath',str(image)],capture_output=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
 if completed.returncode:raise RuntimeError('Windows Chinese OCR unavailable or image unsupported')
 result=json.loads(completed.stdout.decode('utf-8-sig'))
 result['raw_text']=result.get('text','')
 result['text']=re.sub(r'(?<=[\u4e00-\u9fff])[ \t\u3000]+(?=[\u4e00-\u9fff])','',result['raw_text'])
 result['warning']='本地OCR仅供核对；公式、负号、小数、选项及表格可能识别错误，未形成可自动解答的完整题目。'
 return result
