$ErrorActionPreference="Stop"
Set-Location (Join-Path $PSScriptRoot "..")
New-Item -Type Directory -Force dist | Out-Null
python build/build_payload.py
if ($LASTEXITCODE){throw 'Payload build failed'}
$buildDir=(Resolve-Path build).Path
$outDir=(Resolve-Path dist).Path
& 'C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe' /nologo /target:winexe /platform:x64 "/win32icon:$PWD\app\PlateBridge.ico" "/resource:$buildDir\PlateBridge.payload,app.zip" /r:System.IO.Compression.dll /r:System.IO.Compression.FileSystem.dll /r:System.Windows.Forms.dll /r:System.Drawing.dll /r:Microsoft.CSharp.dll "/out:$outDir\PlateBridge-Setup.exe" "$buildDir\Setup.cs"
if ($LASTEXITCODE){throw 'Compiler failed'}
Compress-Archive -LiteralPath 'dist/PlateBridge-Setup.exe' -DestinationPath 'dist/PlateBridge.zip' -Force
