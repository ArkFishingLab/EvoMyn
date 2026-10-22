param([ValidateSet('Start','Stop','Configure','Status')][string]$Action='Start',[switch]$NoBrowser)
$ErrorActionPreference='Stop'
$env:PSModulePath=(Join-Path $PSHOME 'Modules')+[IO.Path]::PathSeparator+$env:PSModulePath
$workspace=Split-Path $PSScriptRoot -Parent
$runtime=Join-Path $workspace 'artifacts/local-memory-mcp'
$python=Join-Path $runtime '.venv/Scripts/python.exe'
$dashboard=Join-Path $runtime 'dashboard.py'
$stateFile=Join-Path $runtime 'dashboard-process.json'
$manager=Join-Path $runtime 'manage.ps1'
$base='http://127.0.0.1:18768'

function Get-OwnedDashboard {
    if(!(Test-Path -LiteralPath $stateFile)){return $null}
    $saved=Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
    $instance=Get-Process -Id $saved.process_id -ErrorAction SilentlyContinue
    if(!$instance){return $null}
    if($instance.StartTime.ToUniversalTime().Ticks -ne ([datetime]$saved.started_utc).ToUniversalTime().Ticks){throw 'Dashboard PID was reused. Refusing to manage another process.'}
    $details=Get-CimInstance Win32_Process -Filter "ProcessId=$($instance.Id)"
    if($instance.Path -ne $python -or !$details.CommandLine.Contains($dashboard)){throw 'Dashboard identity changed. Refusing to manage another process.'}
    return $instance
}

function Invoke-BridgeManager([string]$operation){
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $manager $operation -Json
    if($LASTEXITCODE -ne 0){throw 'MCP bridge management failed. Check logs/cloud.stderr.log.'}
}

if(!(Test-Path -LiteralPath $python) -or !(Test-Path -LiteralPath $manager)){
    throw 'This shortcut uses the existing private workspace. For a new installation, extract the public package and run Start.cmd.'
}
$lockStream=$null
$lockDeadline=[DateTime]::UtcNow.AddSeconds(30)
while(!$lockStream){
    try{$lockStream=[IO.File]::Open((Join-Path $runtime '.current-lifecycle.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)}
    catch [IO.IOException]{
        if([DateTime]::UtcNow -gt $lockDeadline){throw 'Another start or stop is still busy. Please retry.'}
        Start-Sleep -Milliseconds 250
    }
}
try {
if($Action -eq 'Status'){
    $owned=Get-OwnedDashboard
    Invoke-BridgeManager 'Status'
    Write-Output ('Dashboard running: '+[bool]$owned)
    exit 0
}
if($Action -eq 'Stop'){
    Invoke-BridgeManager 'Stop' | Out-Null
    $owned=Get-OwnedDashboard
    if($owned){
        taskkill.exe /PID $owned.Id /T /F | Out-Null
        if($LASTEXITCODE -ne 0){throw 'Could not stop the owned dashboard.'}
    }
    Write-Output 'MCP bridge and dashboard stopped. Your data is preserved.'
    exit 0
}
$owned=Get-OwnedDashboard
if(!$owned){
    foreach($port in @(18768,18770,18772,18773)){
        $socket=[Net.Sockets.TcpClient]::new()
        try{
            $socket.Connect('127.0.0.1',$port)
            throw "Port $port is already in use by an unmanaged process."
        }catch [Net.Sockets.SocketException]{}finally{$socket.Dispose()}
    }
    $logs=Join-Path $runtime 'logs'
    New-Item -ItemType Directory -Path $logs -Force | Out-Null
    $stamp=Get-Date -Format 'yyyyMMdd-HHmmss-ffff'
    $owned=Start-Process -FilePath $python -ArgumentList @('-X','utf8','-u',('"'+$dashboard+'"')) -WorkingDirectory $runtime -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs "dashboard.$stamp.stdout.log") -RedirectStandardError (Join-Path $logs "dashboard.$stamp.stderr.log") -PassThru
    @{process_id=$owned.Id;started_utc=$owned.StartTime.ToUniversalTime().ToString('o');python=$python} | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding utf8
}
$ready=$false
$deadline=[DateTime]::UtcNow.AddSeconds(30)
while([DateTime]::UtcNow -lt $deadline){
    try{
        $reply=Invoke-WebRequest -UseBasicParsing -Uri ($base+'/healthz') -TimeoutSec 2
        $health=$reply.Content | ConvertFrom-Json
        if($health.ok -and $health.service -eq 'personal-memory-mcp'){$ready=$true;break}
    }catch{}
    if(!(Get-OwnedDashboard)){throw 'Dashboard exited. Check the newest logs/dashboard.*.stderr.log.'}
    Start-Sleep -Milliseconds 250
}
if(!$ready){throw 'Dashboard readiness timed out. Check logs/dashboard.*.stderr.log.'}
Invoke-BridgeManager 'Start' | Out-Null
$target=if($Action -eq 'Configure'){$base+'/setup/'}else{$base+'/memory/'}
if(!$NoBrowser){Start-Process $target}
Write-Output ('EvoMyn is ready: '+$target)
} finally {
    if($lockStream){$lockStream.Dispose()}
}
