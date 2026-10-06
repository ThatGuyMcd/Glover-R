# Glover-R live native command logging. Windows PowerShell 5.1 compatible.
# Dot-sourced after the inherited function definitions, before its main try.
$env:PYTHONUNBUFFERED = '1'
$env:PYTHONIOENCODING = 'utf-8:backslashreplace'
try {
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
    $OutputEncoding = [Console]::OutputEncoding
} catch { Write-Host 'Console encoding could not be changed; UTF-8 log files remain enabled.' }

function Invoke-NativeLogged([string]$Executable, [string[]]$Arguments, [string]$NativeLog) {
    $clock = [Diagnostics.Stopwatch]::StartNew()
    Write-Host ('[REQUEST] ' + $Executable + ' ' + ($Arguments -join ' ')) -ForegroundColor Cyan
    Write-Host ('[LOG] ' + $NativeLog) -ForegroundColor DarkGray
    $directory = Split-Path -Parent $NativeLog
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $writer = New-Object System.IO.StreamWriter($NativeLog, $true, $utf8)
    $writer.AutoFlush = $true
    $oldPreference = $ErrorActionPreference
    $code = 1
    try {
        $writer.WriteLine('[REQUEST] ' + $Executable + ' ' + ($Arguments -join ' '))
        # -CommandType Application may return several executable locations.
        # Select one in normal command-precedence order BEFORE reading Source.
        # Casting an array of Source paths to string concatenates them and
        # would turn two valid wsl.exe installations into one invalid command.
        $resolved = @(Get-Command -Name $Executable -CommandType Application -ErrorAction Stop -TotalCount 1)
        if ($resolved.Count -ne 1 -or [string]::IsNullOrWhiteSpace([string]$resolved[0].Source)) {
            throw ('Expected one native executable for: ' + $Executable)
        }
        $Executable = [string]$resolved[0].Source
        Write-Host ('[RUN] ' + $Executable + ' ' + ($Arguments -join ' ')) -ForegroundColor Cyan
        $writer.WriteLine('[RUN] ' + $Executable + ' ' + ($Arguments -join ' '))
        # Warnings/native stderr do not become terminating errors in PS 5.1.
        # On PS 7, preserve native exit codes independently of this preference.
        $PSNativeCommandUseErrorActionPreference = $false
        $ErrorActionPreference = 'Continue'
        # NativeCommandProcessor writes global:LASTEXITCODE. A local variable
        # with that name masks the engine's result (Boot.8 always returned 1).
        # Scope both the failure sentinel and the read explicitly so even a
        # caller's script/local LASTEXITCODE cannot hide the native exit code.
        $global:LASTEXITCODE = 1
        & $Executable @Arguments 2>&1 | ForEach-Object {
            $line = [string]$_
            $writer.WriteLine($line)
            Write-Host $line
        }
        $code = [int]$global:LASTEXITCODE
    } catch {
        # A lookup/launch failure belongs in the command log as well as the
        # parent transcript. Never turn an old LASTEXITCODE into a new success.
        $writer.WriteLine('[ERROR] ' + $_.Exception.Message)
        Write-Host ('[ERROR] ' + $_.Exception.Message) -ForegroundColor Red
        throw
    } finally {
        $ErrorActionPreference = $oldPreference
        $clock.Stop()
        $exitLine = '[EXIT] code ' + $code + '; elapsed ' + $clock.Elapsed.TotalSeconds.ToString('F1') + 's'
        $writer.WriteLine($exitLine)
        $writer.Dispose()
        Write-Host $exitLine
    }
    return $code
}

function Set-GloverBuildStage([string]$Stage, [string]$Status, [int]$ExitCode = -1) {
    $path = Join-Path $Root 'generated\glover-native-build.json'
    # SDK scanning can be the first recorded stage in a clean workspace.
    $directory = Split-Path -Parent $path
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    if (Test-Path -LiteralPath $path) {
        $record = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
    } else {
        $record = [pscustomobject]@{ schema_version = 1; game_booted = $false; stages = [pscustomobject]@{} }
    }
    $entry = [pscustomobject]@{
        status = $Status
        exit_code = $ExitCode
        timestamp_utc = [DateTime]::UtcNow.ToString('o')
    }
    $record.stages | Add-Member -MemberType NoteProperty -Name $Stage -Value $entry -Force
    $temporary = $path + '.' + $PID + '.tmp'
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($temporary, ($record | ConvertTo-Json -Depth 8), $utf8)
    Move-Item -LiteralPath $temporary -Destination $path -Force
    Write-Host ('[stage] ' + $Stage + ' : ' + $Status) -ForegroundColor Cyan
}

function Invoke-GloverBuildStage([string]$Stage, [string]$Executable, [string[]]$Arguments, [string]$NativeLog) {
    Set-GloverBuildStage $Stage 'RUNNING'
    try {
        $code = Invoke-NativeLogged $Executable $Arguments $NativeLog
    } catch {
        Set-GloverBuildStage $Stage 'FAILED' 1
        throw
    }
    $status = if ($code -eq 0) { 'PASS' } else { 'FAILED' }
    Set-GloverBuildStage $Stage $status $code
    return $code
}
