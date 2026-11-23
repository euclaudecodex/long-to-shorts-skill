# Installs the long-to-shorts skill for Claude Code and, if present, Codex (Windows).
# Usage: right-click > "Run with PowerShell", or: powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$targets = @(Join-Path $HOME ".claude\skills\long-to-shorts")
if (Test-Path (Join-Path $HOME ".codex")) { $targets += (Join-Path $HOME ".codex\skills\long-to-shorts") }
foreach ($t in $targets) {
    New-Item -ItemType Directory -Force -Path $t | Out-Null
    Copy-Item -Recurse -Force (Join-Path $here "skills\long-to-shorts\*") $t
    Write-Host "Installed to $t"
}
Write-Host ""
Write-Host "Done! Open Claude and say: clip this video: C:\path\to\stream.mp4  (ou: corta esse vídeo)"
