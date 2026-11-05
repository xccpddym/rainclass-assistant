param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path $PSScriptRoot -Parent)
$buildPython = (Get-Command $Python -ErrorAction Stop).Source
$savedPath = $env:PATH
$savedPythonPath = $env:PYTHONPATH
$mockAsset = (Resolve-Path -LiteralPath 'src/rainclass/mock.html').Path
$windowsOcrAsset = (Resolve-Path -LiteralPath 'src/rainclass/ocr_windows.ps1').Path
try {
    $env:PATH = (Split-Path $buildPython -Parent) + ';' + $env:SystemRoot + '\System32;' + $env:SystemRoot
    $env:PYTHONPATH = (Join-Path $PWD '.local/ocr-runtime') + ';' + (Join-Path $PWD 'src')
    & $buildPython -m PyInstaller --noconfirm --windowed --workpath build/v1.0.0 --distpath dist/v1.0.0 --specpath build --name RainClassAssistant --paths src --paths .local/ocr-runtime --collect-all playwright --collect-all rapidocr --collect-all onnxruntime --collect-all cv2 --collect-all omegaconf --collect-all antlr4 --collect-all pyclipper --collect-all shapely --collect-all numpy --add-data "$mockAsset;rainclass" --add-data "$windowsOcrAsset;rainclass" packaging/entry.py
    if ($LASTEXITCODE -ne 0) { throw 'Release build failed' }
} finally { $env:PATH = $savedPath; $env:PYTHONPATH = $savedPythonPath }
if (Test-Path -LiteralPath 'dist/v1.0.0/RainClassAssistant/_internal/icuuc.dll') { throw 'Private ICU conflict' }
