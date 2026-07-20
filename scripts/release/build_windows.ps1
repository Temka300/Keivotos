[CmdletBinding()]
param(
    [string]$Version = "",
    [string]$OutputDirectory = "artifacts"
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
        npm.cmd run check
        npm.cmd run build
    }
    finally {
        Pop-Location
    }

    .\.venv\Scripts\python.exe .\scripts\release\generate_brand_assets.py
    .\.venv\Scripts\pyinstaller.exe --noconfirm --clean `
        --distpath $DistRoot --workpath $WorkRoot `
        .\packaging\windows\Keivotos.spec
    .\.venv\Scripts\pyinstaller.exe --noconfirm --clean --onefile --console `
        --name gallery-dl --distpath $DistRoot --workpath (Join-Path $WorkRoot "gallery-dl") `
        .\packaging\windows\gallery_dl_entry.py

    New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $DistRoot "Keivotos") -Destination $StageRoot -Recurse
    Copy-Item -LiteralPath (Join-Path $DistRoot "gallery-dl.exe") -Destination (Join-Path $StageRoot "gallery-dl.exe")
    $FfmpegPath = (& .\.venv\Scripts\python.exe -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())").Trim()
    Copy-Item -LiteralPath $FfmpegPath -Destination (Join-Path $StageRoot "ffmpeg.exe")
    foreach ($File in @("README.md", "LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md")) {
        Copy-Item -LiteralPath (Join-Path $Root $File) -Destination (Join-Path $StageRoot $File)
    }
    Copy-Item -LiteralPath (Join-Path $Root ".github\SECURITY.md") -Destination (Join-Path $StageRoot "SECURITY.md")
    New-Item -ItemType Directory -Path (Join-Path $StageRoot "docs") -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $Root "docs\user") -Destination (Join-Path $StageRoot "docs\user") -Recurse
    .\.venv\Scripts\python.exe .\scripts\release\collect_licenses.py (Join-Path $StageRoot "licenses")
    $FfmpegLicenseDirectory = Join-Path $StageRoot "licenses\FFmpeg-7.1"
    New-Item -ItemType Directory -Path $FfmpegLicenseDirectory -Force | Out-Null
    & $FfmpegPath -L | Set-Content -LiteralPath (Join-Path $FfmpegLicenseDirectory "LICENSE.txt") -Encoding utf8
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
        & (Join-Path $StageRoot "gallery-dl.exe") --version
        if ($LASTEXITCODE -ne 0) { throw "Packaged gallery-dl version check failed" }
        & (Join-Path $StageRoot "ffmpeg.exe") -version
        if ($LASTEXITCODE -ne 0) { throw "Packaged FFmpeg version check failed" }
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
