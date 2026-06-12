# Clone jgraph/draw-image-export2 into tools/ and install its deps.
# Idempotent: if the clone already exists, just runs `npm install`.

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$toolsDir = Join-Path $repoRoot "tools"
$serverDir = Join-Path $toolsDir "draw-image-export2"

if (-not (Test-Path $toolsDir)) {
    New-Item -ItemType Directory -Path $toolsDir | Out-Null
}

if (-not (Test-Path $serverDir)) {
    Write-Host "Cloning draw-image-export2 ..."
    git clone --depth 1 https://github.com/jgraph/draw-image-export2.git $serverDir
} else {
    Write-Host "draw-image-export2 already cloned at $serverDir"
}

Write-Host "Installing dependencies (this can take a few minutes -- Puppeteer pulls Chrome) ..."
Push-Location $serverDir
try {
    npm install
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "Done. Start the server with:"
Write-Host "  .\scripts\start_export_server.ps1"
