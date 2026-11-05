param([string]$Exe)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
if (-not $Exe) { $Exe = Join-Path $projectRoot 'dist/v1.0.0/RainClassAssistant/RainClassAssistant.exe' }
$resolvedExe = (Resolve-Path -LiteralPath $Exe).Path
$runId = [guid]::NewGuid().ToString()
$reportPath = Join-Path $projectRoot ('reports/exe-check-' + $runId + '.json')
$dataPath = Join-Path $projectRoot ('.local/exe-check-data-' + $runId)
$packedProcess = Start-Process -FilePath $resolvedExe -ArgumentList @('--smoke-test','--smoke-report',('"' + $reportPath + '"'),'--data-dir',('"' + $dataPath + '"')) -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
if (-not $packedProcess.WaitForExit(90000)) {
    Stop-Process -Id $packedProcess.Id
    throw 'EXE smoke test timed out'
}
if ($packedProcess.ExitCode -ne 0) { throw 'EXE smoke test failed; inspect startup diagnostics' }
$result = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
if (-not $result.pass -or -not $result.frozen -or $result.cloud_requests -ne 0) { throw 'Invalid smoke report' }
Write-Host "PASS: $reportPath"
