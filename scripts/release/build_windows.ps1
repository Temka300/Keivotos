[CmdletBinding()]
param(
    [string]$Version = "",
    [string]$OutputDirectory = "artifacts",
    [ValidateSet("windows", "linux", "both")]
    [string]$Target = "windows"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$ProductSource = Get-Content -LiteralPath (Join-Path $Root "backend\product.py") -Raw
$ProductVersionMatch = [regex]::Match($ProductSource, '(?m)^VERSION = "([^"]+)"\r?$')
if (-not $ProductVersionMatch.Success) {
    throw "Could not read VERSION from backend\product.py"
}
$ProductVersion = $ProductVersionMatch.Groups[1].Value
if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = $ProductVersion
}
elseif ($Version -cne $ProductVersion) {
    throw "Requested artifact version $Version does not match product.py version $ProductVersion"
}
if ($Version -notmatch '^[0-9]+(?:\.[0-9]+){2}[A-Za-z0-9._-]*$') {
    throw "Version contains unsafe path characters: $Version"
}

# Linux builds run with Linux dependencies, including when invoked from Windows.
if ($Target -in @("linux", "both")) {
    $LinuxArguments = @("--target", "linux", "--version", $Version, "--output-directory", $OutputDirectory)
    if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
        $LinuxRoot = (& wsl.exe --exec wslpath -u $Root)
        if ($LASTEXITCODE -ne 0) { throw "Could not resolve repository in the default WSL distribution" }
        & wsl.exe --cd $LinuxRoot --exec bash scripts/release/build_linux.sh @LinuxArguments
    }
    else {
        & bash (Join-Path $Root "scripts/release/build_linux.sh") @LinuxArguments
    }
    if ($LASTEXITCODE -ne 0) { throw "Linux portable build failed with exit code $LASTEXITCODE" }
    if ($Target -eq "linux") { return }
}
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "Windows artifacts must be built from Windows PowerShell; use -Target linux here"
}

if (Test-Path -LiteralPath (Join-Path $Root ".venv/bin/python")) {
    throw "This checkout has a Linux virtual environment. Build Windows from a separate Windows checkout to preserve it."
}

$UvCommand = Get-Command uv -ErrorAction SilentlyContinue | Select-Object -First 1
$UvCandidates = @()
if ($null -ne $UvCommand -and $UvCommand.CommandType -eq "Application") {
    $UvCandidates += $UvCommand.Path
}
$UserProfileDirectory = [Environment]::GetFolderPath("UserProfile")
$LocalApplicationDataDirectory = [Environment]::GetFolderPath("LocalApplicationData")
$UvCandidates += @(
    (Join-Path $UserProfileDirectory ".local\bin\uv.exe"),
    (Join-Path $UserProfileDirectory ".cargo\bin\uv.exe"),
    (Join-Path $LocalApplicationDataDirectory "Programs\uv\uv.exe")
)
$UvPath = $UvCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
if (-not $UvPath) {
    throw "uv was not found on PATH or in the standard per-user install locations"
}
$UvPath = (Resolve-Path -LiteralPath $UvPath).Path
$PackagingRoot = Join-Path $Root "packaging\windows"
$DistRoot = Join-Path $PackagingRoot "dist"
$WorkRoot = Join-Path $PackagingRoot "build"
$ArtifactRoot = [System.IO.Path]::GetFullPath((Join-Path $Root $OutputDirectory))
$StageName = "Keivotos-V$Version-windows-x64"
$StageRoot = Join-Path $ArtifactRoot $StageName

function Assert-PathInsideRepository {
    param([Parameter(Mandatory = $true)][string]$Path)

    $Target = [System.IO.Path]::GetFullPath($Path)
    $RepositoryPrefix = $Root.TrimEnd([char[]]@('\', '/')) + [System.IO.Path]::DirectorySeparatorChar
    if (-not $Target.StartsWith($RepositoryPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to use a path outside the repository: $Path"
    }
    return $Target
}

function Get-FreeLoopbackPort {
    $Listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    try {
        $Listener.Start()
        return ([System.Net.IPEndPoint]$Listener.LocalEndpoint).Port
    }
    finally {
        $Listener.Stop()
    }
}

function Test-PortableServer {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string]$LogDirectory
    )

    $Port = Get-FreeLoopbackPort
    $StandardOutput = Join-Path $LogDirectory "portable-smoke-stdout.log"
    $StandardError = Join-Path $LogDirectory "portable-smoke-stderr.log"
    $Process = $null
    try {
        $Process = Start-Process -FilePath $Executable `
            -ArgumentList @("--no-browser", "--port", "$Port") `
            -RedirectStandardOutput $StandardOutput `
            -RedirectStandardError $StandardError `
            -WindowStyle Hidden -PassThru
        $Deadline = [DateTime]::UtcNow.AddSeconds(45)
        while ([DateTime]::UtcNow -lt $Deadline) {
            $Process.Refresh()
            if ($Process.HasExited) {
                $ErrorText = if (Test-Path -LiteralPath $StandardError) {
                    Get-Content -LiteralPath $StandardError -Raw
                } else { "No stderr was captured." }
                throw "Portable server exited before becoming ready (code $($Process.ExitCode)): $ErrorText"
            }
            try {
                $Response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/" -TimeoutSec 2
                if ($Response.StatusCode -eq 200) {
                    return
                }
            }
            catch {
                Start-Sleep -Milliseconds 250
            }
        }
        throw "Portable server did not become ready within 45 seconds"
    }
    finally {
        if ($null -ne $Process) {
            $Process.Refresh()
            if (-not $Process.HasExited) {
                Stop-Process -Id $Process.Id -Force
                Wait-Process -Id $Process.Id -ErrorAction SilentlyContinue
            }
        }
    }
}

function Compress-PortableArchive {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    for ($Attempt = 1; $Attempt -le 10; $Attempt++) {
        try {
            Compress-Archive -LiteralPath $Source -DestinationPath $Destination -CompressionLevel Optimal -ErrorAction Stop
            return
        }
        catch {
            if ($Attempt -eq 10) { throw }
            # Native executable and antivirus handles can linger briefly after
            # the verification commands complete on Windows.
            Start-Sleep -Milliseconds 500
        }
    }
}

$CleanupPaths = @($DistRoot, $WorkRoot, $StageRoot)
foreach ($Path in $CleanupPaths) {
    $null = Assert-PathInsideRepository -Path $Path
}
foreach ($Path in $CleanupPaths) {
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

Push-Location $Root
try {
    & $UvPath sync --locked --python 3.11 --group build
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed with exit code $LASTEXITCODE" }
    Push-Location (Join-Path $Root "frontend")
    try {
        npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw "npm.cmd ci failed" }
        npm.cmd run check
        if ($LASTEXITCODE -ne 0) { throw "npm.cmd run check failed" }
        npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw "npm.cmd run build failed" }
    }
    finally {
        Pop-Location
    }

    .\.venv\Scripts\python.exe .\scripts\release\generate_brand_assets.py
    if ($LASTEXITCODE -ne 0) { throw "Brand generation failed" }
    .\.venv\Scripts\pyinstaller.exe --noconfirm --clean `
        --distpath $DistRoot --workpath $WorkRoot `
        .\packaging\windows\Keivotos.spec
    if ($LASTEXITCODE -ne 0) { throw "Application build failed" }
    $DeliveryJson = & .\.venv\Scripts\python.exe .\scripts\release\delivery_plan.py
    if ($LASTEXITCODE -ne 0) { throw "Delivery requirements could not be loaded" }
    $Delivery = $DeliveryJson | ConvertFrom-Json
    $ModuleTools = @($Delivery.tools | Where-Object { $_.entry_script })
    foreach ($Tool in $ModuleTools) {
        .\.venv\Scripts\pyinstaller.exe --noconfirm --clean --onefile --console `
            --name $Tool.name --distpath $DistRoot --workpath (Join-Path $WorkRoot $Tool.name) `
            $Tool.entry_script
        if ($LASTEXITCODE -ne 0) { throw "Module tool build failed: $($Tool.name)" }
    }

    New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $DistRoot "Keivotos") -Destination $StageRoot -Recurse
    foreach ($Tool in $ModuleTools) {
        $ToolFile = "$($Tool.name).exe"
        Copy-Item -LiteralPath (Join-Path $DistRoot $ToolFile) -Destination (Join-Path $StageRoot $ToolFile)
    }
    $FfmpegPath = (& .\.venv\Scripts\python.exe -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())").Trim()
    if ($LASTEXITCODE -ne 0) { throw "FFmpeg discovery failed" }
    Copy-Item -LiteralPath $FfmpegPath -Destination (Join-Path $StageRoot "ffmpeg.exe")
    foreach ($File in @("README.md", "LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md")) {
        Copy-Item -LiteralPath (Join-Path $Root $File) -Destination (Join-Path $StageRoot $File)
    }
    Copy-Item -LiteralPath (Join-Path $Root ".github\SECURITY.md") -Destination (Join-Path $StageRoot "SECURITY.md")
    New-Item -ItemType Directory -Path (Join-Path $StageRoot "docs") -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $Root "docs\user") -Destination (Join-Path $StageRoot "docs\user") -Recurse
    .\.venv\Scripts\python.exe .\scripts\release\collect_licenses.py (Join-Path $StageRoot "licenses")
    if ($LASTEXITCODE -ne 0) { throw "License collection failed" }
    $FfmpegLicenseDirectory = Join-Path $StageRoot "licenses\FFmpeg-7.1"
    New-Item -ItemType Directory -Path $FfmpegLicenseDirectory -Force | Out-Null
    & $FfmpegPath -L | Set-Content -LiteralPath (Join-Path $FfmpegLicenseDirectory "LICENSE.txt") -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "FFmpeg license check failed" }
    Copy-Item -LiteralPath (Join-Path $Root "packaging\windows\FFMPEG_SOURCE.md") -Destination $FfmpegLicenseDirectory

    $SmokeHome = Join-Path $WorkRoot "portable-smoke-home"
    New-Item -ItemType Directory -Path $SmokeHome -Force | Out-Null
    $PreviousKeivotosHome = $env:KEIVOTOS_HOME
    try {
        $env:KEIVOTOS_HOME = $SmokeHome
        & (Join-Path $StageRoot "Keivotos.exe") --version
        if ($LASTEXITCODE -ne 0) { throw "Packaged Keivotos version check failed" }
        & (Join-Path $StageRoot "Keivotos.exe") --portable-check
        if ($LASTEXITCODE -ne 0) { throw "Packaged Keivotos resource check failed" }
        foreach ($Tool in $Delivery.tools) {
            & (Join-Path $StageRoot "$($Tool.name).exe") $Tool.version_flag
            if ($LASTEXITCODE -ne 0) { throw "Packaged tool version check failed: $($Tool.name)" }
        }
        Test-PortableServer -Executable (Join-Path $StageRoot "Keivotos.exe") -LogDirectory $SmokeHome
    }
    finally {
        if ($null -eq $PreviousKeivotosHome) {
            Remove-Item Env:KEIVOTOS_HOME -ErrorAction SilentlyContinue
        }
        else {
            $env:KEIVOTOS_HOME = $PreviousKeivotosHome
        }
    }

    $ZipPath = Join-Path $ArtifactRoot "$StageName.zip"
    if (Test-Path -LiteralPath $ZipPath) { Remove-Item -LiteralPath $ZipPath -Force }
    Compress-PortableArchive -Source $StageRoot -Destination $ZipPath
    $Hash = Get-FileHash -Algorithm SHA256 -LiteralPath $ZipPath
    "$($Hash.Hash.ToLowerInvariant())  $($Hash.Path | Split-Path -Leaf)" | Set-Content -LiteralPath "$ZipPath.sha256" -Encoding utf8
    Write-Host "Portable archive: $ZipPath"
}
finally {
    Pop-Location
}
