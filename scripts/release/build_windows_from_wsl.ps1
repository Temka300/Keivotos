# Internal WSL bridge: receives only a curated source copy and build parameters.
[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$RequestFile)
$ErrorActionPreference = "Stop"
$Request = Get-Content -LiteralPath $RequestFile -Raw | ConvertFrom-Json
$Work = Join-Path ([System.IO.Path]::GetTempPath()) ("keivotos-windows-build-" + [guid]::NewGuid().ToString("N"))
$Source = Join-Path $Work "repo"
try {
    New-Item -ItemType Directory -Path $Source | Out-Null
    Get-ChildItem -LiteralPath $Request.source -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $Source -Recurse
    }
    # These variables belong to this child PowerShell process only.
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $Source ".venv"
    foreach ($Name in @("VIRTUAL_ENV", "DANBOORU_USERNAME", "DANBOORU_API_KEY",
                        "KEIVOTOS_MIGRATE_LEGACY_HOME", "KEIVOTOS_LAN_HOST", "KEIVOTOS_DEVELOPER_LAN")) {
        Remove-Item "Env:$Name" -ErrorAction SilentlyContinue
    }
    $env:KEIVOTOS_HOME = Join-Path $Work "app-home"
    & (Join-Path $Source "scripts/release/build_windows.ps1") -Target windows -Version $Request.version
    # The builder throws on failed steps. Do not use a stale LASTEXITCODE here.
    $ArchiveName = "Keivotos-V$($Request.version)-windows-x64.zip"
    foreach ($Name in @($ArchiveName, "$ArchiveName.sha256")) {
        $InputFile = Join-Path $Source "artifacts/$Name"
        $OutputFile = Join-Path $Request.output $Name
        if (-not (Test-Path -LiteralPath $InputFile -PathType Leaf)) {
            throw "Windows builder did not produce $Name"
        }
        # CreateNew refuses to overwrite an existing artifact, including a race.
        $InputStream = [System.IO.File]::OpenRead($InputFile)
        try {
            $OutputStream = [System.IO.File]::Open($OutputFile, [System.IO.FileMode]::CreateNew)
            try { $InputStream.CopyTo($OutputStream) }
            finally { $OutputStream.Dispose() }
        }
        finally { $InputStream.Dispose() }
    }
    Write-Host "Windows portable archive: $(Join-Path $Request.output $ArchiveName)"
}
finally {
    if (Test-Path -LiteralPath $Work) {
        Remove-Item -LiteralPath $Work -Recurse -Force
    }
}
