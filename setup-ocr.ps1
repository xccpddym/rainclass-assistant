$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
# Official PyPI packages are installed only inside this project.
$ocrTarget = Join-Path $PSScriptRoot '.local/ocr-runtime'
python -m pip install --disable-pip-version-check --target $ocrTarget --upgrade -r requirements-ocr.lock --index-url https://pypi.org/simple
if ($LASTEXITCODE -ne 0) { throw 'Offline OCR setup failed' }
Write-Output 'Offline OCR is ready. Classroom images are processed locally.'
