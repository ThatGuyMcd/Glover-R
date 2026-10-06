# Real command-discovery/process tests. Requires only the invoking PowerShell
# and small temporary command scripts; does not invoke WSL, Git or game tools.
# Windows PowerShell 5.1 compatible. No Pester or global PATH changes required.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$HelperPath,
    [Parameter(Mandatory=$true)][string]$WorkDir,
    [string]$PythonExe
)
$ErrorActionPreference = 'Stop'
$originalPath = $env:Path
$checks = 0
function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw ('RUNNER TEST FAILED: ' + $Message) }
    $script:checks += 1
}
$Root = Join-Path $WorkDir 'native workspace'
$null = New-Item -ItemType Directory -Force -Path $Root
$first = Join-Path $WorkDir 'first tool directory'
$second = Join-Path $WorkDir 'second tool directory'
$null = New-Item -ItemType Directory -Force -Path $first,$second
$windowsHost = [Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT
$tool = if ($windowsHost) { 'glover-runner-probe.cmd' } else { 'glover-runner-probe' }
$firstTool = Join-Path $first $tool
$secondTool = Join-Path $second $tool
$utf8 = New-Object System.Text.UTF8Encoding($false)
foreach ($item in @(@($firstTool,'FIRST'), @($secondTool,'SECOND'))) {
    if ($windowsHost) {
        $body = '@echo off' + "`r`n" + 'echo PROBE:' + $item[1] + "`r`n" +
                'echo ARG:%~1' + "`r`n" + 'echo warning: runner test stderr 1>&2' + "`r`n" +
                'exit /b %~2' + "`r`n"
    } else {
        $body = '#!/bin/sh' + "`n" + "printf '%s\n' 'PROBE:" + $item[1] + "'" + "`n" +
                'printf ''ARG:%s\n'' "$1"' + "`n" +
                'printf ''warning: runner test stderr\n'' >&2' + "`n" + 'exit "$2"' + "`n"
    }
    [IO.File]::WriteAllText($item[0], $body, $utf8)
    if (-not $windowsHost) {
        & chmod +x $item[0]
        if ($LASTEXITCODE -ne 0) { throw 'Could not make the temporary fixture executable.' }
    }
}
$aliasCreated = $false
try {
    . $HelperPath
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $Root 'generated'))) 'stage fixture starts without a generated directory'
    Set-GloverBuildStage 'fixture.clean-stage' 'RUNNING'
    $statusPath = Join-Path $Root 'generated/glover-native-build.json'
    Assert-True (Test-Path -LiteralPath $statusPath) 'first stage creates its status directory and file'
    $initial = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
    Assert-True ($initial.stages.PSObject.Properties['fixture.clean-stage'].Value.status -eq 'RUNNING') 'first stage is recorded in a clean workspace'
    $separator = [IO.Path]::PathSeparator
    $env:Path = $first + $separator + $second + $separator + $originalPath
    # Create the multiple-result case from Boot.7 using two real files.
    # -All keeps this fixture explicit even on hosts with different defaults.
    $all = @(Get-Command -Name $tool -CommandType Application -All -ErrorAction Stop)
    Assert-True ($all.Count -ge 2) 'the test must discover both application paths'
    Assert-True ($all[0].Source -eq $firstTool) 'first application must follow PATH precedence'
    [string]$oldExecutable = $all.Source
    Assert-True ($oldExecutable.Contains($firstTool) -and $oldExecutable.Contains($secondTool)) 'old scalar conversion must reproduce concatenated paths'
    $caught = $false
    try { & $oldExecutable 'unused' '0' *> $null } catch { $caught = $true }
    Assert-True $caught 'concatenated executable string must fail before running'

    $argument = 'a path containing spaces'
    # Boot.9: independently reproduce the variable-scope bug with a real child.
    # The local sentinel stays at 1; NativeCommandProcessor writes global scope.
    function Invoke-OldExitCodePattern([string]$Probe, [int]$Expected) {
        $LASTEXITCODE = 1
        & $Probe 'scope probe' ([string]$Expected) *> $null
        return [pscustomobject]@{ Local = $LASTEXITCODE; Global = $global:LASTEXITCODE }
    }
    $oldPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $PSNativeCommandUseErrorActionPreference = $false
        foreach ($expected in @(0,17)) {
            $old = Invoke-OldExitCodePattern $firstTool $expected
            Assert-True ($old.Local -eq 1) 'old function-local sentinel masks the native result'
            Assert-True ($old.Global -eq $expected) 'native process writes its actual result to global scope'
        }
    } finally { $ErrorActionPreference = $oldPreference }
    Write-Host 'OLD_EXIT_CODE_SHADOW_REPRODUCED'

    # Deliberately seed a stale GLOBAL result. A completed native command must
    # replace it. With powershell.exe -File the top-level script can run in the
    # session scope, so script: is not an independent shadow in that situation.
    # Genuine caller-local isolation is tested in its own function below.
    $global:LASTEXITCODE = 999
    $log = Join-Path $Root 'build/logs/first.log'
    $code = Invoke-NativeLogged $tool @($argument,'0') $log
    Assert-True ($code -is [int] -and $code -eq 0) 'runner returns only one native exit code'
    $text = [IO.File]::ReadAllText($log)
    Assert-True ($text.Contains('[RUN] ' + $firstTool + ' ')) 'log records exactly the first executable'
    Assert-True (-not $text.Contains($secondTool)) 'no second executable leaks into the launch'
    Assert-True ($text.Contains('PROBE:FIRST')) 'selected first executable actually ran'
    Assert-True ($text.Contains('ARG:' + $argument)) 'spaced argument survives invocation'
    Assert-True ($text.Contains('warning: runner test stderr')) 'stderr warning is logged without failure'
    Assert-True ($ErrorActionPreference -eq 'Stop') 'error preference is restored after success'

    $env:Path = $second + $separator + $first + $separator + $originalPath
    $log = Join-Path $Root 'build/logs/reordered.log'
    $code = Invoke-NativeLogged $tool @($argument,'0') $log
    Assert-True ($code -eq 0) 'reordered PATH invocation succeeds'
    Assert-True ([IO.File]::ReadAllText($log).Contains('PROBE:SECOND')) 'precedence is not hard-coded to a particular location'

    $log = Join-Path $Root 'build/logs/explicit.log'
    $code = Invoke-NativeLogged $firstTool @($argument,'0') $log
    Assert-True ($code -eq 0) 'explicit spaced executable path succeeds'
    Assert-True ([IO.File]::ReadAllText($log).Contains('PROBE:FIRST')) 'explicit path wins over PATH'

    Set-Alias -Name $tool -Value Write-Output -Scope Script
    $aliasCreated = $true
    $log = Join-Path $Root 'build/logs/alias.log'
    $code = Invoke-NativeLogged $tool @($argument,'0') $log
    Assert-True ($code -eq 0) 'application-only discovery ignores a same-name PowerShell alias'
    Assert-True ([IO.File]::ReadAllText($log).Contains('PROBE:SECOND')) 'alias did not intercept native execution'
    Remove-Item -LiteralPath ('Alias:' + $tool)
    $aliasCreated = $false

    $log = Join-Path $Root 'build/logs/nonzero.log'
    $code = Invoke-GloverBuildStage 'fixture.nonzero' $firstTool @($argument,'17') $log
    Assert-True ($code -is [int] -and $code -eq 17) 'native exit 17 survives the wrapper'
    $status = Get-Content -LiteralPath (Join-Path $Root 'generated/glover-native-build.json') -Raw | ConvertFrom-Json
    $entry = $status.stages.PSObject.Properties['fixture.nonzero'].Value
    Assert-True ($entry.status -eq 'FAILED' -and $entry.exit_code -eq 17) 'nonzero exit is recorded as failed'
    Assert-True ([IO.File]::ReadAllText($log).Contains('[EXIT] code 17')) 'exit code is in command log'

    # Boot.10: this must be a FUNCTION-LOCAL shadow, not script: at the
    # powershell.exe -File entry point (where Script may be Global).
    # The log already proves the production runner returns real exit codes;
    # do not change it merely to satisfy an incorrect test-scope assumption.
    function Test-CallerExitCodeIsolation([string]$Probe, [string]$Argument, [string]$StatusFile) {
        $local:LASTEXITCODE = 999
        $localSlot = Get-Variable -Name LASTEXITCODE -Scope Local
        $globalSlot = Get-Variable -Name LASTEXITCODE -Scope Global
        Assert-True (-not [object]::ReferenceEquals($localSlot, $globalSlot)) 'shadow fixture owns a distinct function-local variable'
        # A constant-success wrapper or reuse of the previous result must fail.
        foreach ($expected in @(0,7,0,23,0)) {
            $log = Join-Path $Root ('build/logs/sequence-' + $checks + '.log')
            $code = Invoke-GloverBuildStage 'fixture.exit-sequence' $Probe @($Argument,[string]$expected) $log
            Assert-True ($code -is [int] -and $code -eq $expected) ('exact native exit is returned: ' + $expected)
            Assert-True ($global:LASTEXITCODE -eq $expected) 'engine-global exit code follows the real process result'
            $status = Get-Content -LiteralPath $StatusFile -Raw | ConvertFrom-Json
            $entry = $status.stages.PSObject.Properties['fixture.exit-sequence'].Value
            $expectedStatus = if ($expected -eq 0) { 'PASS' } else { 'FAILED' }
            Assert-True ($entry.status -eq $expectedStatus -and $entry.exit_code -eq $expected) 'stage status follows the real process result'
            Assert-True ($local:LASTEXITCODE -eq 999) 'function-local caller shadow is neither read nor modified'
            Assert-True ($ErrorActionPreference -eq 'Stop') 'error preference remains restored'
        }
        Write-Host 'FUNCTION_LOCAL_EXIT_CODE_ISOLATION_PASS'
    }
    Test-CallerExitCodeIsolation $firstTool $argument $statusPath

    # Exercise a real .exe as well as the .cmd fixture on Windows. Python is
    # already running the build and this test, so no new dependency is required.
    if (-not [string]::IsNullOrWhiteSpace($PythonExe)) {
        $child = Join-Path $WorkDir 'native exit probe.py'
        $body = "import sys`nprint('PYTHON_PROBE', flush=True)`n" +
                "print('PYTHON_ARG:' + sys.argv[1], flush=True)`n" +
                "print('PYTHON_STDERR', file=sys.stderr, flush=True)`n" +
                "sys.exit(int(sys.argv[2]))`n"
        [IO.File]::WriteAllText($child,$body,$utf8)
        foreach ($expected in @(0,17,0)) {
            $log = Join-Path $Root ('build/logs/python-' + $checks + '.log')
            $code = Invoke-GloverBuildStage 'fixture.python-native' $PythonExe @('-u',$child,$argument,[string]$expected) $log
            Assert-True ($code -is [int] -and $code -eq $expected) 'real Python executable exit is returned exactly'
            $text = [IO.File]::ReadAllText($log)
            Assert-True ($text.Contains('PYTHON_PROBE')) 'real executable output is captured'
            Assert-True ($text.Contains('PYTHON_ARG:' + $argument)) 'real executable receives spaced argument'
            Assert-True ($text.Contains('PYTHON_STDERR')) 'real executable stderr is captured'
        }
    }

    $log = Join-Path $Root 'build/logs/missing.log'
    $global:LASTEXITCODE = 0
    $caught = $false
    try {
        $null = Invoke-GloverBuildStage 'inputs.sdk-symbols' 'glover-definitely-missing-executable-8.exe' @() $log
    } catch { $caught = $true }
    Assert-True $caught 'missing native executable cannot reuse a previous success'
    $text = [IO.File]::ReadAllText($log)
    Assert-True ($text.Contains('[ERROR]') -and $text.Contains('[EXIT] code 1')) 'lookup failure is recorded in the dedicated log'
    $status = Get-Content -LiteralPath (Join-Path $Root 'generated/glover-native-build.json') -Raw | ConvertFrom-Json
    $entry = $status.stages.PSObject.Properties['inputs.sdk-symbols'].Value
    Assert-True ($entry.status -eq 'FAILED' -and $entry.exit_code -eq 1) 'SDK stage records failure even before child launch'
    Assert-True ($ErrorActionPreference -eq 'Stop') 'error preference is restored after failure'

    # Parse all maintained PowerShell scripts without invoking the actual build.
    $project = Split-Path -Parent $PSScriptRoot
    foreach ($folder in @('scripts','native/scripts','tests')) {
        foreach ($file in Get-ChildItem -LiteralPath (Join-Path $project $folder) -Filter '*.ps1' -Recurse -File) {
            $tokens = $null; $parseErrors = $null
            $null = [System.Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$parseErrors)
            Assert-True ($parseErrors.Count -eq 0) ('PowerShell parses: ' + $file.Name)
        }
    }
    Write-Host ('POWERSHELL_RUNNER_TESTS_PASS checks=' + $checks)
    exit 0
} catch {
    Write-Host $_.Exception.ToString()
    exit 1
} finally {
    if ($aliasCreated) { Remove-Item -LiteralPath ('Alias:' + $tool) -ErrorAction SilentlyContinue }
    $env:Path = $originalPath
}
