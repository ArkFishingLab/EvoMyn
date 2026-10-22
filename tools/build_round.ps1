param(
    [string]$IdfPath = $env:IDF_PATH,
    [string]$BuildDir,
    [string]$Python = 'python',
    [string]$LogName = 'firmware-build.log',
    [switch]$Incremental,
    [switch]$Check
)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path $PSScriptRoot -Parent
if (-not $IdfPath -or -not (Test-Path -LiteralPath (Join-Path $IdfPath 'tools/idf.py'))) {
    throw 'Set IDF_PATH or pass -IdfPath after activating the ESP-IDF environment.'
}
if (-not $BuildDir) { throw 'Pass -BuildDir with an ASCII-only source/build mirror path.' }
$mirror = [IO.Path]::GetFullPath($BuildDir)
$source = Join-Path $workspace 'xiaozhi-firmware'
if ($mirror -match '[^\x00-\x7f]') { throw 'BuildDir must contain only ASCII characters for ESP-IDF on Windows.' }
if ($mirror.StartsWith($source.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) -or $mirror.TrimEnd('\') -eq $source.TrimEnd('\') -or $source.StartsWith($mirror.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'BuildDir must be separate from the source checkout and its ancestors.'
}
if ($LogName -ne [IO.Path]::GetFileName($LogName)) { throw 'LogName must be a filename.' }
if ($Check) { Write-Output "Configuration valid: $mirror"; exit 0 }
New-Item -ItemType Directory -Force -Path $mirror | Out-Null
# Keep SDK configuration and downloaded dependencies; no deletion.
robocopy $source $mirror /E /XD build managed_components .git /XF sdkconfig sdkconfig.old /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -gt 7) { throw 'Source mirror copy failed.' }
$logs = Join-Path $workspace 'artifacts/build-logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$log = Join-Path $logs $LogName
$env:PYTHONUTF8 = '1'
$actions = @('reconfigure', 'build')
if ($Incremental) { $actions = @('build') }
# Tool paths and proxy settings come from the caller's ESP-IDF shell.
& $Python (Join-Path $IdfPath 'tools/idf.py') -C $mirror @actions *> $log
$result = $LASTEXITCODE
Get-Content -LiteralPath $log -Tail 25
exit $result
