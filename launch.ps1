param([switch]$Rebuild, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$localPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $localPython)) {
    Write-Host 'Creating the local Python environment...'
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 or newer is required. Install Python and try again.' }
}
& $localPython -c "import fastapi, uvicorn, numpy, pandas, sklearn, joblib, multipart"
if ($LASTEXITCODE -ne 0) {
    & $localPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency setup failed. Retry this launcher to resume installation.' }
}
& $localPython -m app.artifacts
$repairArtifacts = $LASTEXITCODE -ne 0
if ($Rebuild -or $repairArtifacts) {
    & $localPython -c "from app.launch import port_in_use; import sys; sys.exit(1 if port_in_use() else 0)"
    if ($LASTEXITCODE -ne 0) { throw 'Stop the server using port 8000 before rebuilding, then retry.' }
}
if ($Rebuild -or $repairArtifacts) {
    Write-Host 'Training LineGuard from bundled SKAB data...'
    & $localPython -m app.train
    if ($LASTEXITCODE -ne 0) { throw 'Training failed. See the message above.' }
}
if ($Rebuild -or $repairArtifacts) {
    Write-Host 'Training the independent NASA engine prognostics profile...'
    & $localPython -m app.prognostics
    if ($LASTEXITCODE -ne 0) { throw 'Engine training failed. See the message above.' }
}
if ($Rebuild -or $repairArtifacts) {
    & $localPython -m app.alerting
    if ($LASTEXITCODE -ne 0) { throw 'Alert evidence generation failed.' }
    & $localPython -m app.research
    if ($LASTEXITCODE -ne 0) { throw 'Research diagnostics generation failed.' }
    & $localPython -m app.policy
    if ($LASTEXITCODE -ne 0) { throw 'Maintenance policy simulation failed.' }
    & $localPython -c "from app.explain import build; build()"
    if ($LASTEXITCODE -ne 0) { throw 'Explanation reference generation failed.' }
    & $localPython -m app.artifacts --write
    if ($LASTEXITCODE -ne 0) { throw 'Artifact verification failed.' }
}
Write-Host ''
Write-Host 'LineGuard is starting at http://127.0.0.1:8000' -ForegroundColor Green
Write-Host 'Everything stays on this computer. Press Ctrl+C to stop.'
if ($NoBrowser) { & $localPython -m app.launch --no-browser } else { & $localPython -m app.launch }
