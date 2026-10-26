[CmdletBinding()]
param([string]$Runtime = 'D:\AppData\RemNoteBulkImporter\material-venv')
$ErrorActionPreference = 'Stop'
$MaterialPython = Join-Path $Runtime 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $MaterialPython)) {
    python -m venv $Runtime
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed' }
}
& $MaterialPython -m pip install -r (Join-Path $PSScriptRoot 'material-requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Material dependencies failed to install' }
& $MaterialPython -c 'import pymupdf, PIL, bs4, markdown_it, lxml, requests, opencc; print("Material runtime ready")'
if ($LASTEXITCODE -ne 0) { throw 'Material runtime verification failed' }
