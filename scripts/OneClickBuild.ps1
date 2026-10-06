[CmdletBinding()]
param(
    [string]$Rom,
    [string[]]$Platforms,
    [switch]$PreflightOnly,
    [switch]$PrepareOnly,
    [switch]$NoPackage,
    [switch]$NoLaunch,
    [switch]$RepairDependencies,
    [switch]$CollectDiagnostics
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$env:PYTHONUNBUFFERED = '1'
$env:PYTHONIOENCODING = 'utf-8:backslashreplace'
try {
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
    $OutputEncoding = [Console]::OutputEncoding
} catch { Write-Host 'Console encoding unchanged; build log files use UTF-8.' }
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $Root

function Banner([string]$Text) {
    Write-Host ''
    Write-Host ('=' * 78) -ForegroundColor DarkCyan
    Write-Host ('  ' + $Text) -ForegroundColor Cyan
    Write-Host ('=' * 78) -ForegroundColor DarkCyan
}

function Find-PythonCommand {
    foreach ($name in @('py.exe', 'python.exe')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) {
            $prefix = @()
            if ($name -eq 'py.exe') { $prefix = @('-3') }
            $oldPreference = $ErrorActionPreference
            try {
                $ErrorActionPreference = 'Continue'
                & $command.Source @prefix -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' *> $null
                $code = $LASTEXITCODE
            } finally { $ErrorActionPreference = $oldPreference }
            if ($code -eq 0) {
                return @{ Executable = $command.Source; Prefix = $prefix }
            }
        }
    }
    return $null
}

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + $env:Path
}

try {
    $Version = (Get-Content -LiteralPath (Join-Path $Root 'VERSION') -Raw).Trim()
    Banner ('Glover-R ' + $Version + ' - One Click Builder')
    Write-Host 'Native build: CPU/RSP generation, compilation and platform packaging.' -ForegroundColor Cyan
    Write-Host 'The 1.0.0 release has been tested in Windows gameplay. Test each new build.' -ForegroundColor Yellow
    Write-Host 'Your ROM stays local. The original ROM and existing Rocket-R project are not modified.'
    $Python = Find-PythonCommand
    if (-not $Python) {
        $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
        if (-not $winget) { throw 'Python 3.10+ is required. Install Python, then run ONE-CLICK-BUILD.cmd again.' }
        $answer = Read-Host 'Python 3.10+ was not found. Install Python 3.12 using winget? [Y/n]'
        if ($answer -match '^[nN]') { throw 'Python is required; installation was declined.' }
        $oldPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            & $winget.Source install --id Python.Python.3.12 --exact --accept-package-agreements --accept-source-agreements
            $installCode = $LASTEXITCODE
        } finally { $ErrorActionPreference = $oldPreference }
        Refresh-Path
        $Python = Find-PythonCommand
        if (-not $Python) {
            Write-Host ('Python installation/discovery needs attention (winget exit ' + $installCode + ').') -ForegroundColor Yellow
            Write-Host 'Close this window and run ONE-CLICK-BUILD.cmd again after Python installation completes.'
            exit 20
        }
    }
    if ($CollectDiagnostics) {
        $prefix = @($Python.Prefix)
        & $Python.Executable @prefix -u -B (Join-Path $Root 'scripts\collect_diagnostics.py')
        exit $LASTEXITCODE
    }
    if (-not $PreflightOnly -and -not (Get-Command git.exe -ErrorAction SilentlyContinue)) {
        $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
        if (-not $winget) { throw 'Git for Windows is required for the pinned source/dependency checkout.' }
        $answer = Read-Host 'Git was not found. Install Git for Windows using winget? [Y/n]'
        if ($answer -match '^[nN]') { throw 'Git installation was declined.' }
        $oldPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            & $winget.Source install --id Git.Git --exact --accept-package-agreements --accept-source-agreements
            $gitCode = $LASTEXITCODE
        } finally { $ErrorActionPreference = $oldPreference }
        Refresh-Path
        if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) {
            Write-Host ('Git installation/discovery needs attention (exit ' + $gitCode + ').')
            exit 20
        }
    }
    if (-not $Platforms -or $Platforms.Count -eq 0) {
        if ($PreflightOnly) {
            $Platforms = @('1', '2')
        } else {
            Write-Host ''
            Write-Host 'Select native targets (Windows also includes the matching Linux x64 package):'
            Write-Host '  [1] Windows x64'
            Write-Host '  [2] Linux x86-64 / Steam Deck'
            Write-Host '  [3] Linux ARM64'
            Write-Host '  [4] Android ARM64'
            Write-Host '  [A] All four'
            $choice = Read-Host 'One or more choices, default 1,2'
            if ([string]::IsNullOrWhiteSpace($choice)) { $choice = '1,2' }
            $Platforms = @($choice)
        }
    }
    if ([string]::IsNullOrWhiteSpace($Rom)) {
        if ($env:GLOVER_ROM -and (Test-Path -LiteralPath $env:GLOVER_ROM -PathType Leaf)) {
            $Rom = $env:GLOVER_ROM
        } elseif (Test-Path -LiteralPath (Join-Path $Root 'build\private\glover.us.z64') -PathType Leaf) {
            $Rom = Join-Path $Root 'build\private\glover.us.z64'
        } else {
            try {
                Add-Type -AssemblyName System.Windows.Forms
                $dialog = New-Object System.Windows.Forms.OpenFileDialog
                $dialog.Title = 'Select the valid Glover (USA) ROM - .n64 is accepted'
                $dialog.Filter = 'N64 ROM (*.z64;*.v64;*.n64)|*.z64;*.v64;*.n64|All files (*.*)|*.*'
                if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { $Rom = $dialog.FileName }
                $dialog.Dispose()
            } catch { Write-Host 'File picker unavailable; using a path prompt.' }
            if ([string]::IsNullOrWhiteSpace($Rom)) { $Rom = Read-Host 'Full path to your valid Glover USA ROM' }
        }
    }
    if ([string]::IsNullOrWhiteSpace($Rom) -or -not (Test-Path -LiteralPath $Rom -PathType Leaf)) {
        throw 'No readable ROM was selected. Choose Glover (USA).n64, not the damaged zero-filled .z64.'
    }
    if ($PreflightOnly) {
        $arguments = @('-u', '-B', (Join-Path $Root 'scripts\preflight.py'), '--rom', $Rom, '--platforms', ($Platforms -join ','))
    } else {
        $arguments = @('-u', '-B', (Join-Path $Root 'scripts\native_build.py'), '--rom', $Rom, '--platforms', ($Platforms -join ','))
        if ($PrepareOnly) { $arguments += '--prepare-only' }
        if ($NoPackage) { $arguments += '--no-package' }
        if ($NoLaunch) { $arguments += '--no-launch' }
        if ($RepairDependencies) { $arguments += '--repair-dependencies' }
    }
    $prefix = @($Python.Prefix)
    $oldPreference = $ErrorActionPreference
    try {
        # Native stderr is diagnostic output, not an automatic PowerShell 5.1
        # terminating error. The process exit code determines success/failure.
        $ErrorActionPreference = 'Continue'
        & $Python.Executable @prefix @arguments 2>&1 | ForEach-Object { Write-Host ([string]$_) }
        $code = [int]$LASTEXITCODE
    } finally { $ErrorActionPreference = $oldPreference }
    exit $code
} catch {
    Write-Host ('BUILD STOPPED: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
