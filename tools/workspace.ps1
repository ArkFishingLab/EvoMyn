param(
    [ValidateSet('Start','Stop','Configure','Status','Prepare')][string]$Action='Start',
    [string]$Workspace=(Split-Path $PSScriptRoot -Parent),
    [switch]$NoBrowser
)
$ErrorActionPreference='Stop'
$env:PSModulePath=(Join-Path $PSHOME 'Modules')+[IO.Path]::PathSeparator+$env:PSModulePath
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
. (Join-Path $PSScriptRoot 'prepare_runtime.ps1') -Workspace $Workspace
$lifecycleLock=$null
try {
    $workspaceRoot=[IO.Path]::GetFullPath($Workspace)
    Assert-PlainPath $workspaceRoot
    if (!(Test-Path -LiteralPath $workspaceRoot -PathType Container)) { throw 'Source workspace does not exist.' }
    $runtime=Join-Path $workspaceRoot 'artifacts/local-memory-mcp'
    $kind=Get-SourceRuntimeKind $runtime
    if ($kind -eq 'legacy') {
        if ($Action -eq 'Prepare') { Write-Output 'Existing private installation preserved.'; exit 0 }
        $legacy=Join-Path $workspaceRoot 'tools/current_memory.ps1'
        Assert-PlainPath $legacy
        if (!(Test-Path -LiteralPath $legacy -PathType Leaf)) { throw 'Missing private lifecycle manager.' }
        $arguments=@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$legacy,'-Action',$Action)
        if ($NoBrowser) { $arguments+='-NoBrowser' }
        & powershell.exe @arguments
        exit $LASTEXITCODE
    }
    # An empty checkout Stop/Status is read-only and never installs dependencies.
    if ($kind -eq 'new' -and $Action -in @('Stop','Status')) {
        Write-Output 'No local runtime is installed.'
        exit 0
    }
    if ($Action -eq 'Prepare') {
        Initialize-SourceRuntime $workspaceRoot
        exit 0
    }
    if ($kind -eq 'new') { $runtime=Initialize-SourceRuntime $workspaceRoot }
    Assert-RuntimePaths $runtime
    $bootstrap=Join-Path $runtime 'bootstrap.ps1'
    if (!(Test-Path -LiteralPath $bootstrap -PathType Leaf)) { throw 'Incomplete portable runtime. Run Prepare before Start.' }
    # Serialize source Start/Stop/Configure around bootstrap's separate dependency
    # lock and the portable launcher's process identity/lifecycle lock.
    $deadline=[DateTime]::UtcNow.AddMinutes(30)
    while (!$lifecycleLock) {
        try { $lifecycleLock=[IO.File]::Open((Join-Path $runtime '.workspace-lifecycle.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None) }
        catch [IO.IOException] {
            if ([DateTime]::UtcNow -gt $deadline) { throw 'Another workspace lifecycle operation is busy.' }
            Start-Sleep -Milliseconds 100
        }
    }
    Assert-RuntimePaths $runtime
    $arguments=@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$bootstrap,'-Root',$runtime,'-Action',$Action.ToLowerInvariant())
    if ($NoBrowser) { $arguments+='-NoBrowser' }
    & powershell.exe @arguments
    exit $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine('Workspace: '+$_.Exception.Message)
    exit 1
} finally { if ($lifecycleLock) { $lifecycleLock.Dispose() } }
