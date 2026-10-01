param(
    [string]$Version = "v1.5.2"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
# Stable package name required by existing automatic update clients.
$AppName = "SecretShopBot-E7"
$DisplayName = "Epic7 Assist Bot"
$ReleaseRoot = Join-Path $ProjectRoot "release"
$DistRoot = Join-Path $ProjectRoot "dist"
$BuildRoot = Join-Path $ProjectRoot "build"
$NormalizedVersion = if ($Version.StartsWith("v")) { $Version } else { "v$Version" }
$NumericVersion = if ($NormalizedVersion.StartsWith("v")) { $NormalizedVersion.Substring(1) } else { $NormalizedVersion }
$CoreVersion = ($NumericVersion -split '-', 2)[0]
$CoreParts = @($CoreVersion.Split('.') | ForEach-Object { [int]$_ })
while ($CoreParts.Count -lt 3) { $CoreParts += 0 }
$PreReleaseBuild = 0
if ($NumericVersion -match '-(?:alpha|beta|rc)[.-]?(\d+)$') {
    $PreReleaseBuild = [int]$Matches[1]
}
$FileVersionTuple = "$($CoreParts[0]), $($CoreParts[1]), $($CoreParts[2]), $PreReleaseBuild"
$PackageName = "$AppName-$NormalizedVersion"
$PackageDir = Join-Path $ReleaseRoot $PackageName
$StagingPackageDir = $PackageDir
$ZipPath = Join-Path $ReleaseRoot "$PackageName.zip"

Set-Location $ProjectRoot

Write-Host "== $DisplayName (EAB) release build =="
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

Write-Host "Checking executable icon..."
$IconPath = Join-Path $ProjectRoot "assets\icons\app_icon_multi_size.ico"
$IconCacheDir = Join-Path $ProjectRoot "assets\icons\_generated"
if (Test-Path $IconCacheDir) {
    Remove-Item -LiteralPath $IconCacheDir -Recurse -Force
}
if (-not (Test-Path $IconPath)) {
    throw "Executable icon was not found: $IconPath"
}

Write-Host "Generating Windows version metadata..."
@"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($FileVersionTuple),
    prodvers=($FileVersionTuple),
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
          StringStruct(u'FileDescription', u'$DisplayName (EAB)'),
          StringStruct(u'FileVersion', u'$NumericVersion'),
          StringStruct(u'InternalName', u'SecretShopBot-E7'),
          StringStruct(u'OriginalFilename', u'SecretShopBot-E7.exe'),
          StringStruct(u'ProductName', u'$DisplayName'),
          StringStruct(u'ProductVersion', u'$NumericVersion'),
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
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

$BuiltDir = Join-Path $DistRoot $AppName
if (-not (Test-Path $BuiltDir)) {
    throw "Build failed: $BuiltDir was not created."
}
if (-not (Test-Path (Join-Path $BuiltDir "SecretShopBot-Updater.exe"))) {
    throw "Automatic updater executable is missing from the build."
}

Write-Host "Preparing release package..."
if (Test-Path $StagingPackageDir) {
    Remove-Item -LiteralPath $StagingPackageDir -Recurse -Force
}
Copy-Item -LiteralPath $BuiltDir -Destination $StagingPackageDir -Recurse

Write-Host "Validating runtime-only release contents..."
python -m build_support.release_assets --validate $StagingPackageDir
if ($LASTEXITCODE -ne 0) {
    throw "Release contains missing runtime files or unwanted development files."
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
Write-Host "Upload BOTH the zip and its .sha256.txt file to GitHub Releases:"
Write-Host "  https://github.com/pelierze/SecretShopBot-E7/releases/new"
