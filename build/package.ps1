param([string]$Wix = "wix")
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot
$dist = Join-Path $root "dist"
New-Item -ItemType Directory -Force $dist | Out-Null
& $Wix build "$PSScriptRoot/PlateBridge.wxs" -arch x64 -d "AppDir=$root/app" -intermediateFolder "$dist/obj" -out "$dist/PlateBridge.msi"
if ($LASTEXITCODE) { throw "PlateBridge MSI build failed." }
