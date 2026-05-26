param(
    [string]$Version = "v1.2.1"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppName = "SecretShopBot-E7"
$ReleaseRoot = Join-Path $ProjectRoot "release"
$DistRoot = Join-Path $ProjectRoot "dist"
$BuildRoot = Join-Path $ProjectRoot "build"
$NormalizedVersion = if ($Version.StartsWith("v")) { $Version } else { "v$Version" }
$NumericVersion = if ($NormalizedVersion.StartsWith("v")) { $NormalizedVersion.Substring(1) } else { $NormalizedVersion }
$PackageName = "$AppName-$NormalizedVersion"
$PackageDir = Join-Path $ReleaseRoot $PackageName
$StagingPackageDir = $PackageDir
$ZipPath = Join-Path $ReleaseRoot "$PackageName.zip"

Set-Location $ProjectRoot

Write-Host "== SecretShopBot-E7 release build =="
Write-Host "Version: $NormalizedVersion"
Write-Host ""

if (-not (Test-Path "main.py")) {
    throw "main.py was not found. Run this script from the project root."
}

Write-Host "Checking Python..."
python --version

Write-Host "Installing/updating Python dependencies..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

Write-Host "Syncing executable icon from assets/icons/app_icon.png..."
@'
from pathlib import Path
from PIL import Image

project_root = Path.cwd()
png_path = project_root / "assets" / "icons" / "app_icon.png"
ico_path = project_root / "assets" / "icons" / "app_icon.ico"

if not png_path.exists():
    raise SystemExit(f"Icon source not found: {png_path}")

with Image.open(png_path) as image:
    image.save(
        ico_path,
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
    )

print(f"Updated {ico_path}")
'@ | python -

Write-Host "Generating Windows version metadata..."
@"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($($NumericVersion.Replace('.', ', ')), 0),
    prodvers=($($NumericVersion.Replace('.', ', ')), 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'040904B0',
        [
          StringStruct(u'CompanyName', u'pelierze'),
          StringStruct(u'FileDescription', u'SecretShopBot-E7 for Epic Seven'),
          StringStruct(u'FileVersion', u'$NumericVersion.0'),
          StringStruct(u'InternalName', u'SecretShopBot-E7'),
          StringStruct(u'OriginalFilename', u'SecretShopBot-E7.exe'),
          StringStruct(u'ProductName', u'SecretShopBot-E7'),
          StringStruct(u'ProductVersion', u'$NumericVersion.0'),
        ]
      )
    ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"@ | Set-Content -Path (Join-Path $ProjectRoot "file_version_info.txt") -Encoding ASCII

Write-Host "Cleaning previous build output..."
if (Test-Path $DistRoot) {
    Remove-Item -LiteralPath $DistRoot -Recurse -Force
}
if (Test-Path $BuildRoot) {
    Remove-Item -LiteralPath $BuildRoot -Recurse -Force
}
if (Test-Path $PackageDir) {
    try {
        Remove-Item -LiteralPath $PackageDir -Recurse -Force
    }
    catch {
        $Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $StagingPackageDir = Join-Path $ReleaseRoot "$PackageName-staging-$Timestamp"
        Write-Host "Existing release folder is in use. Using staging folder:"
        Write-Host "  $StagingPackageDir"
    }
}
if (Test-Path $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}
New-Item -ItemType Directory -Path $ReleaseRoot -Force | Out-Null

Write-Host "Building Windows app with PyInstaller..."
python -m PyInstaller `
    --noconfirm `
    SecretShopBot-E7.spec

$BuiltDir = Join-Path $DistRoot $AppName
if (-not (Test-Path $BuiltDir)) {
    throw "Build failed: $BuiltDir was not created."
}

Write-Host "Preparing release package..."
if (Test-Path $StagingPackageDir) {
    Remove-Item -LiteralPath $StagingPackageDir -Recurse -Force
}
Copy-Item -LiteralPath $BuiltDir -Destination $StagingPackageDir -Recurse

$ReadmeSource = Join-Path $ProjectRoot "README.md"
if (Test-Path $ReadmeSource) {
    Copy-Item -LiteralPath $ReadmeSource -Destination (Join-Path $StagingPackageDir "README.md")
}

$DeploySource = Join-Path $ProjectRoot "DEPLOY.md"
if (Test-Path $DeploySource) {
    Copy-Item -LiteralPath $DeploySource -Destination (Join-Path $StagingPackageDir "DEPLOY.md")
}

$SecuritySource = Join-Path $ProjectRoot "SECURITY.md"
if (Test-Path $SecuritySource) {
    Copy-Item -LiteralPath $SecuritySource -Destination (Join-Path $StagingPackageDir "SECURITY.md")
}

Write-Host "Creating zip package..."
$ZipCreated = $false
for ($Attempt = 1; $Attempt -le 5; $Attempt++) {
    try {
        if (Test-Path $ZipPath) {
            Remove-Item -LiteralPath $ZipPath -Force
        }
        Start-Sleep -Seconds 2
        Compress-Archive -Path $StagingPackageDir -DestinationPath $ZipPath -Force
        $ZipCreated = $true
        break
    }
    catch {
        if ($Attempt -eq 5) {
            throw
        }
        Write-Host "Zip attempt $Attempt failed, retrying..."
        Start-Sleep -Seconds 3
    }
}

if (-not $ZipCreated) {
    throw "Zip package was not created."
}

$Hash = Get-FileHash -Algorithm SHA256 -LiteralPath $ZipPath
$HashPath = "$ZipPath.sha256.txt"
"$($Hash.Hash)  $(Split-Path -Leaf $ZipPath)" | Set-Content -Path $HashPath -Encoding ASCII

Write-Host ""
Write-Host "Release package created:"
Write-Host "  $ZipPath"
Write-Host "SHA256:"
Write-Host "  $($Hash.Hash)"
Write-Host ""
Write-Host "Upload the zip file to GitHub Releases:"
Write-Host "  https://github.com/pelierze/SecretShopBot-E7/releases/new"
