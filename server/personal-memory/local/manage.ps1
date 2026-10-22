param([ValidateSet('Start','Stop','Restart','Status')][string]$Action='Status',[switch]$Json)
$ErrorActionPreference='Stop'
$env:PSModulePath=(Join-Path $PSHOME 'Modules')+[IO.Path]::PathSeparator+$env:PSModulePath
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
$python=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$launcher=Join-Path $PSScriptRoot 'launcher.py'
if (!(Test-Path -LiteralPath $python) -or !(Test-Path -LiteralPath $launcher)) {
    Write-Error 'Local runtime unavailable. Run Start.cmd first.'
    exit 1
}
if ($Action -eq 'Restart') {
    & $python -X utf8 $launcher --root $PSScriptRoot bridge-stop --json | Out-Null
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $command='bridge-start'
} else {
    $command=@{Start='bridge-start';Stop='bridge-stop';Status='bridge-status'}[$Action]
}
$arguments=@('-X','utf8',$launcher,'--root',$PSScriptRoot,$command)
if ($Json) { $arguments+='--json' }
& $python @arguments
exit $LASTEXITCODE
