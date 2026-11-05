param(
    [Parameter(Mandatory=$true)][string]$Url,
    [ValidateRange(1,3600)][int]$Seconds = 180
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$entryUri = [Uri]$Url
if (-not $entryUri.IsAbsoluteUri -or $entryUri.Scheme -ne 'https' -or $entryUri.UserInfo) {
    throw 'An absolute HTTPS URL without credentials is required.'
}
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
# Separate from the mock browser profile.
$profilePath = Join-Path $PSScriptRoot '.local/readonly/rainclass-edge-profile'
$reportPath = Join-Path $PSScriptRoot ('reports/readonly-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.jsonl')
python -m rainclass.diagnostics --url $Url --allow-host $entryUri.DnsSafeHost --seconds $Seconds --profile $profilePath --output $reportPath
if ($LASTEXITCODE -ne 0) { throw 'Read-only diagnostics stopped with an error.' }
Write-Host "Report: $reportPath"
