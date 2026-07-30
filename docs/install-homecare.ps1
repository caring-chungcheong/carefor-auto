# Homecare Hub - desktop app shortcut installer
#
# Usage (paste into PowerShell, press Enter):
#   iex (irm "https://caring-chungcheong.github.io/carefor-auto/install-homecare.ps1")
#
# Why chrome --app instead of a PWA install:
#   - The Chungcheong hub already owns the /carefor-auto/ scope, so a second PWA
#     in that scope is not installable at all.
#   - A managed (policy-controlled) Chrome can hide the "Install app" menu entirely.
#   - chrome --app=<URL> bypasses both and gives the same result: a window with no address bar.
#
# ASCII ONLY on purpose. PowerShell 5.1 reads a BOM-less .ps1 as cp949, so Korean text
# in this file would corrupt the parser and mangle paths (measured: the shortcut path
# became garbage and Save() threw FileNotFoundException).

$ErrorActionPreference = 'Continue'

$HUB     = 'https://script.google.com/a/macros/caring.co.kr/s/AKfycbyYBYMgBqAQMmVyNb4cD-LxB_bHZQnDAuigcU6yYvpx5vVQN3sCLFOmRVFNeNvOgZ_hhA/exec'
$ICO_URL = 'https://caring-chungcheong.github.io/carefor-auto/icons/homecare.ico'
$NAME    = [char]0xBC29 + [char]0xBB38 + [char]0xC694 + [char]0xC591 + ' ' +
           [char]0xACF5 + [char]0xC720 + [char]0xD5C8 + [char]0xBE0C   # "Bangmun-yoyang Gongyu-heobeu"

# ---- find a browser: Chrome first, Edge as fallback (both support --app) ----
$cands = @(
  "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
  "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
  "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
  "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
  "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
)
$browser = $cands | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $browser) {
  Write-Host 'FAILED: Chrome/Edge not found. Install Chrome and run again.' -ForegroundColor Red
  return
}

# ---- icon (optional; keep going if the download fails) ----
$icoDir = Join-Path $env:LOCALAPPDATA 'caring-hub'
try { New-Item -ItemType Directory -Force -Path $icoDir -ErrorAction Stop | Out-Null } catch {}
$ico = Join-Path $icoDir 'homecare.ico'
try {
  Invoke-WebRequest -Uri $ICO_URL -OutFile $ico -UseBasicParsing -TimeoutSec 20 -ErrorAction Stop
} catch {
  Write-Host 'WARN: icon download failed - using the browser default icon.' -ForegroundColor Yellow
  $ico = $null
}

# ---- desktop shortcut ----
# Use GetFolderPath('Desktop'): on OneDrive-redirected PCs $env:USERPROFILE\Desktop
# does not exist and Save() fails (measured on this machine).
$desktop = [Environment]::GetFolderPath('Desktop')
$lnk = Join-Path $desktop ($NAME + '.lnk')

$w = New-Object -ComObject WScript.Shell
$s = $w.CreateShortcut($lnk)
$s.TargetPath       = $browser
$s.Arguments        = "--app=$HUB"          # standalone window, no address bar / tabs
$s.WorkingDirectory = Split-Path $browser
$s.Description      = 'Homecare shared hub (app window)'
if ($ico -and (Test-Path $ico)) { $s.IconLocation = "$ico,0" }
$s.Save()

if (Test-Path $lnk) {
  Write-Host ''
  Write-Host 'DONE - a shortcut was created on your Desktop.' -ForegroundColor Green
  Write-Host ("  file    : " + $lnk)
  Write-Host ("  browser : " + (Split-Path $browser -Leaf))
  Write-Host '  One click opens it as an app window (no address bar).'
  Write-Host '  You must sign in with your caring.co.kr account the first time.'
} else {
  Write-Host 'FAILED: could not create the shortcut.' -ForegroundColor Red
}
