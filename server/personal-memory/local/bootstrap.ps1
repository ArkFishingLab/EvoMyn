param(
    [ValidateSet('start','stop','status','configure','client-config','stdio')][string]$Action='start',
    [string]$Root=$PSScriptRoot, [switch]$NoBrowser,
    [ValidateSet('json','toml')][string]$Format='json'
)
$ErrorActionPreference='Stop'
$Action=$Action.ToLowerInvariant()
$ProgressPreference='SilentlyContinue'
$env:UV_NO_MODIFY_PATH='1'
$env:PSModulePath=(Join-Path $PSHOME 'Modules')+[IO.Path]::PathSeparator+$env:PSModulePath
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
$runtimeRoot=[IO.Path]::GetFullPath($Root)
$launcher=Join-Path $runtimeRoot 'launcher.py'
$venvPython=Join-Path $runtimeRoot '.venv\Scripts\python.exe'
$requirements=Join-Path $runtimeRoot 'requirements.txt'
$logDirectory=Join-Path $runtimeRoot 'logs'
$lockStream=$null

function Find-InstalledPython {
    foreach ($candidate in @('py.exe','python.exe','python3.exe')) {
        $found=Get-Command $candidate -ErrorAction SilentlyContinue
        if (!$found -or $found.Source -like '*\WindowsApps\*') { continue }
        $arguments=@()
        if ($candidate -eq 'py.exe') { $arguments=@('-3') }
        try {
            & $found.Source @arguments -c 'import sys;sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { return @{File=$found.Source;Arguments=$arguments} }
        } catch { }
    }
    return $null
}

function Invoke-InstallNative {
    param([string]$File,[string[]]$Arguments,[string]$Log)
    $savedPreference=$ErrorActionPreference
    $ErrorActionPreference='Continue'
    try { & $File @Arguments *>> $Log; return $LASTEXITCODE }
    finally { $ErrorActionPreference=$savedPreference }
}

function Install-LocalEnvironment {
    if (!(Test-Path -LiteralPath $requirements)) { throw 'Missing requirements.txt. Extract the complete portable package.' }
    $dependencyHash=(Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash
    $marker=Join-Path $runtimeRoot '.venv\requirements.sha256'
    if ((Test-Path -LiteralPath $venvPython) -and (Test-Path -LiteralPath $marker)) {
        if ((Get-Content -LiteralPath $marker -Raw).Trim() -eq $dependencyHash) { return }
    }
    $installLog=Join-Path $logDirectory 'bootstrap.log'
    $uvCommand=Get-Command uv.exe -ErrorAction SilentlyContinue
    $uv=$null
    if ($uvCommand) { $uv=$uvCommand.Source }
    if (!(Test-Path -LiteralPath $venvPython)) {
        $installed=Find-InstalledPython
        if ($installed) {
            Write-Host 'Creating the local Python environment...'
            $pythonFile=$installed.File; $pythonArguments=$installed.Arguments
            $venvArguments=@($pythonArguments)+@('-m','venv',(Join-Path $runtimeRoot '.venv'))
            $installExit=Invoke-InstallNative -File $pythonFile -Arguments $venvArguments -Log $installLog
            if ($installExit -ne 0) { throw 'Could not create .venv. See logs/bootstrap.log.' }
        } else {
            Write-Host 'Installing a local managed Python 3.11 runtime...'
            if (!$uv) {
                throw 'Install Python 3.11+ from https://www.python.org/downloads/windows/ or uv from https://docs.astral.sh/uv/, then run Start.cmd.'
            }
            $env:UV_PYTHON_INSTALL_DIR=Join-Path $runtimeRoot '.tools\python'
            $env:UV_CACHE_DIR=Join-Path $runtimeRoot '.tools\uv-cache'
            $installExit=Invoke-InstallNative -File $uv -Arguments @('venv','--python','3.11','--managed-python',(Join-Path $runtimeRoot '.venv')) -Log $installLog
            if ($installExit -ne 0) { throw 'Could not install managed Python. See logs/bootstrap.log.' }
        }
    }
    Write-Host 'Installing pinned dependencies. First run may take several minutes; see logs/bootstrap.log.'
    if ($uv) { $installExit=Invoke-InstallNative -File $uv -Arguments @('pip','install','--python',$venvPython,'--requirements',$requirements) -Log $installLog }
    else { $installExit=Invoke-InstallNative -File $venvPython -Arguments @('-m','pip','install','--disable-pip-version-check','--requirement',$requirements) -Log $installLog }
    if ($installExit -ne 0) { throw 'Dependency installation failed. Check network access and logs/bootstrap.log, then run Start again.' }
    [IO.File]::WriteAllText($marker,$dependencyHash,[System.Text.UTF8Encoding]::new($false))
}

try {
    if (!(Test-Path -LiteralPath $launcher) -or !(Test-Path -LiteralPath (Join-Path $runtimeRoot 'app'))) {
        throw 'Extract the complete portable package before running these commands.'
    }
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    # Stop/status do not download or install anything.
    if ($Action -notin @('stop','status','stdio')) {
        $deadline=[DateTime]::UtcNow.AddMinutes(30)
        while (!$lockStream) {
            try { $lockStream=[IO.File]::Open((Join-Path $runtimeRoot '.bootstrap.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None) }
            catch [IO.IOException] {
                if ([DateTime]::UtcNow -gt $deadline) { throw 'Another dependency installation is still busy.' }
                Start-Sleep -Milliseconds 250
            }
        }
        Install-LocalEnvironment
        $lockStream.Dispose(); $lockStream=$null
    }
    $runArguments=@('-X','utf8',$launcher,'--root',$runtimeRoot,$Action)
    if ($NoBrowser) { $runArguments+='--no-browser' }
    if ($Action -eq 'client-config') { $runArguments+=@('--format',$Format) }
    if (Test-Path -LiteralPath $venvPython) { & $venvPython @runArguments }
    else {
        $installed=Find-InstalledPython
        if (!$installed) {
            if ($Action -in @('stop','status')) { Write-Host 'No local runtime is installed.'; exit 0 }
            throw 'Python is unavailable. Run Start.cmd first.'
        }
        $pythonFile=$installed.File; $pythonArguments=$installed.Arguments
        & $pythonFile @pythonArguments @runArguments
    }
    exit $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine('Personal MCP: '+$_.Exception.Message)
    exit 1
} finally {
    if ($lockStream) { $lockStream.Dispose() }
}
