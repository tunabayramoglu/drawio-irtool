# Start the local drawio export server on port 8005.
# Default port 8000 is avoided because it tends to clash with throwaway
# `python -m http.server` instances. Override with -Port if you want.

param(
    [int]$Port = 8005
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$serverDir = Join-Path $repoRoot "tools\draw-image-export2"

if (-not (Test-Path $serverDir)) {
    Write-Error "Server not installed. Run scripts\setup_export_server.ps1 first."
    exit 1
}

Write-Host "Starting draw-image-export2 on port $Port"
Write-Host "Set DRAWIO_EXPORT_URL=http://localhost:$Port in your shell so"
Write-Host "irtool render and the legacy converter pick up the right endpoint."
Write-Host ""

Push-Location $serverDir
try {
    $env:PORT = "$Port"
    npm start
} finally {
    Pop-Location
}
