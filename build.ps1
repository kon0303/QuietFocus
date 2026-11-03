# Build QuietFocus:
#   dist\QuietFocus.exe                  single-file launcher (extracts runtime beside itself)
#   dist\QuietFocus\                     portable folder
#   dist\QuietFocus-1.0.1-portable.zip   portable archive
#
#   .\build.ps1
#   powershell -ExecutionPolicy Bypass -File .\build.ps1

param(
    [string]$Python = "python",
    [string]$Csc = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$vendor = Join-Path $root ".vendor"
if (Test-Path $vendor) {
    $env:PYTHONPATH = $vendor
}

# 1. Build the portable, self-contained application folder.
$pyinstaller = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onedir",
    "--windowed",
    "--name", "QuietFocus",
    "--icon", (Join-Path $root "assets\icon.ico"),
    "--add-data", ((Join-Path $root "assets") + ";assets"),
    "--hidden-import", "pystray._win32",
    "--exclude-module", "numpy",
    "--exclude-module", "pandas",
    "--exclude-module", "matplotlib",
    "--exclude-module", "scipy",
    "--exclude-module", "lxml",
    "--version-file", (Join-Path $root "version_info.txt"),
    "--distpath", (Join-Path $root "dist"),
    "--workpath", (Join-Path $root "build-portable"),
    "--specpath", (Join-Path $root "build-portable"),
    (Join-Path $root "app.py")
)
& $Python @pyinstaller
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE"
}

$portable = Join-Path $root "dist\QuietFocus"
$zip = Join-Path $root "dist\QuietFocus-1.0.1-portable.zip"
Copy-Item (Join-Path $root "README.md") -Destination $portable -Force
Copy-Item (Join-Path $root "LICENSE") -Destination $portable -Force
"1.0.1" | Set-Content (Join-Path $portable "version.txt") -Encoding ascii
if (Test-Path $zip) {
    Remove-Item $zip -Force
}
Compress-Archive -Path $portable -DestinationPath $zip -Force

# 2. Build the single-file launcher. It extracts the portable payload beside
# itself (or under %LOCALAPPDATA% when that folder is read-only), avoiding the
# PyInstaller onefile %TEMP% extraction failure on locked-down systems.
if (-not (Test-Path $Csc)) {
    throw "C# compiler not found: $Csc"
}
$launcherOut = Join-Path $root "dist\QuietFocus.exe"
& $Csc /nologo /target:winexe /optimize+ `
    "/out:$launcherOut" `
    "/win32icon:$(Join-Path $root 'assets\icon.ico')" `
    "/resource:$zip,payload.zip" `
    /r:System.IO.Compression.dll `
    /r:System.IO.Compression.FileSystem.dll `
    /r:System.Windows.Forms.dll `
    /r:System.Drawing.dll `
    (Join-Path $root "launcher\Program.cs") `
    (Join-Path $root "launcher\AssemblyInfo.cs")
if ($LASTEXITCODE -ne 0) {
    throw "Launcher compilation failed with exit code $LASTEXITCODE"
}

Write-Host "Built:"
Write-Host "  $launcherOut"
Write-Host "  $portable"
Write-Host "  $zip"
