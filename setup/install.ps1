param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('cpu', 'gpu')]
    [string]$Device,
    [switch]$KasperskyCompatibility
)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol =
    [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$Root = Split-Path -Parent $PSScriptRoot
$Tools = Join-Path $Root 'tools'
$UvVersion = '0.12.5'
$UvSha256 = '4c4d49d8738847d9b71ba319e49a5688c93eac0fe6204b1df24e98528dddf39a'
$PythonVersion = '3.11.16'
$Uv = Join-Path $Tools 'uv\uv.exe'
$Venv = Join-Path $Root "venv-$Device"
$Python = Join-Path $Venv 'Scripts\python.exe'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Tools 'python'
$env:UV_CACHE_DIR = Join-Path $Tools 'uv-cache'
$env:UV_PYTHON_PREFERENCE = 'only-managed'
$env:UV_PYTHON_INSTALL_BIN = '0'
$env:UV_NO_CONFIG = '1'
Remove-Item Env:UV_NATIVE_TLS -ErrorAction SilentlyContinue
$env:UV_SYSTEM_CERTS = 'true'
$env:UV_HTTP_RETRIES = '5'
$env:UV_HTTP_TIMEOUT = '60'
$env:UV_HTTP_CONNECT_TIMEOUT = '20'
$env:UV_EXCLUDE_NEWER = '2026-08-23'
$Scratch = Join-Path ([IO.Path]::GetTempPath()) ('FaceRetouchSheets-' + [Guid]::NewGuid().ToString('N'))
$Log = Join-Path $Root 'install.log'
$ExitCode = 0

function Invoke-Step {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Exit code ${LASTEXITCODE}: $Exe $($Arguments -join ' ')"
    }
}

function Invoke-WebDownloadWithRetry {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][string]$OutFile,
        [int]$Attempts = 4
    )
    $lastError = $null
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            Remove-Item -LiteralPath $OutFile -Force -ErrorAction SilentlyContinue
            Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $OutFile -TimeoutSec 120
            if (-not (Test-Path -LiteralPath $OutFile -PathType Leaf)) {
                throw 'download finished without creating the destination file'
            }
            return
        }
        catch {
            $lastError = $_.Exception
            Remove-Item -LiteralPath $OutFile -Force -ErrorAction SilentlyContinue
            if ($attempt -lt $Attempts) {
                Write-Warning "Download failed ($($lastError.Message)). Retry $attempt/$Attempts..."
                Start-Sleep -Seconds ([Math]::Min(8, 2 * $attempt))
            }
        }
    }
    throw "Download failed after $Attempts attempts: $($lastError.Message)"
}

Start-Transcript -LiteralPath $Log -Force | Out-Null
try {
    if (-not [Environment]::Is64BitOperatingSystem) {
        throw 'This package requires 64-bit Windows.'
    }
    Write-Host '[1/5] Preparing uv and private Python...'
    if (-not (Test-Path -LiteralPath $Uv -PathType Leaf)) {
        New-Item -ItemType Directory -Path $Scratch -Force | Out-Null
        $UvZip = Join-Path $Scratch 'uv.zip'
        $UvUrl = "https://releases.astral.sh/github/uv/releases/download/$UvVersion/uv-x86_64-pc-windows-msvc.zip"
        Invoke-WebDownloadWithRetry -Uri $UvUrl -OutFile $UvZip
        if ((Get-FileHash -LiteralPath $UvZip -Algorithm SHA256).Hash -ne $UvSha256) {
            throw 'The downloaded uv archive failed SHA-256 verification.'
        }
        Expand-Archive -LiteralPath $UvZip -DestinationPath $Scratch
        $Extracted = Get-ChildItem -LiteralPath $Scratch -Filter 'uv.exe' -File -Recurse | Select-Object -First 1
        if (-not $Extracted) { throw 'uv.exe is missing from the downloaded archive.' }
        New-Item -ItemType Directory -Path (Split-Path -Parent $Uv) -Force | Out-Null
        Copy-Item -LiteralPath $Extracted.FullName -Destination $Uv
    }
    Invoke-Step $Uv @('--version')
    Invoke-Step $Uv @('python', 'install', '--no-bin', $PythonVersion)
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        Invoke-Step $Uv @('venv', '--relocatable', '--allow-existing', '--python', $PythonVersion, $Venv)
    }
    Invoke-Step $Python @('-c', "import struct, sys; assert sys.version_info[:3] == (3,11,16); assert struct.calcsize('P') == 8")

    Write-Host "[2/5] Installing dependencies for $Device..."
    $Dependencies = @('-r', (Join-Path $PSScriptRoot 'requirements.txt'))
    if ($Device -eq 'gpu') {
        $Dependencies += @('-r', (Join-Path $PSScriptRoot 'requirements-gpu.txt'))
    }
    else {
        $Dependencies += 'onnxruntime==1.26.0'
    }
    if ($KasperskyCompatibility) {
        Write-Warning 'Kaspersky mode: certificate verification is bypassed only for pypi.org and files.pythonhosted.org during package installation.'
        Invoke-Step $Python @('-m', 'ensurepip')
        $PackageExe = $Python
        $PackageArgs = @('-m', 'pip', '--isolated', 'install', '--disable-pip-version-check', '--index-url', 'https://pypi.org/simple',
            '--trusted-host', 'pypi.org', '--trusted-host', 'files.pythonhosted.org',
            '--timeout', '60', '--retries', '5', '--only-binary=:all:')
    }
    else {
        $PackageExe = $Uv
        $PackageArgs = @('pip', 'install', '--python', $Python, '--only-binary=:all:')
    }
    try {
        Invoke-Step $PackageExe ($PackageArgs + $Dependencies)
        Invoke-Step $PackageExe ($PackageArgs + @('--no-deps', 'insightface==1.0.1'))
    }
    catch {
        Write-Host 'For a connection timeout, check access to pypi.org and files.pythonhosted.org.'
        throw
    }

    Write-Host '[3/5] Preparing the SCRFD model...'
    Invoke-Step $Python @((Join-Path $PSScriptRoot 'install_model.py'))

    Write-Host '[4/5] Checking Tkinter, PSD reader and model inference...'
    $SmokeDevice = if ($Device -eq 'gpu') { 'auto' } else { 'cpu' }
    Invoke-Step $Python @((Join-Path $PSScriptRoot 'check_install.py'), $SmokeDevice)

    Write-Host '[5/5] Saving launcher configuration...'
    $Device | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'runtime-device.txt') -Encoding ASCII
    Write-Host 'Installation completed successfully. Run run.bat.'
}
catch {
    $ExitCode = 1
    Write-Host "Installation failed: $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    if (Test-Path -LiteralPath $Scratch) {
        Remove-Item -LiteralPath $Scratch -Recurse -Force -ErrorAction SilentlyContinue
    }
    Stop-Transcript | Out-Null
}
exit $ExitCode
