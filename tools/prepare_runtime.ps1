param([string]$Workspace=(Split-Path $PSScriptRoot -Parent))

# Source assembly deliberately needs only Windows PowerShell, not Python.
# Keep this allowlist aligned with the runtime subset in package_public_release.py.
function Get-ReparseTag([string]$Path) {
    if (-not ('PersonalMemory.ReparseInfo' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
namespace PersonalMemory {
    public static class ReparseInfo {
        [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
        private struct FindData {
            public uint Attributes;
            public System.Runtime.InteropServices.ComTypes.FILETIME Creation, Access, Write;
            public uint SizeHigh, SizeLow, ReparseTag, Reserved;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst=260)] public string Name;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst=14)] public string AlternateName;
        }
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
        private static extern IntPtr FindFirstFileW(string path, out FindData data);
        [DllImport("kernel32.dll")]
        private static extern bool FindClose(IntPtr handle);
        public static uint ReadTag(string path) {
            FindData data;
            IntPtr handle=FindFirstFileW(path, out data);
            if(handle == new IntPtr(-1)) throw new Win32Exception(Marshal.GetLastWin32Error());
            try { return data.ReparseTag; }
            finally { FindClose(handle); }
        }
    }
}
'@
    }
    return [PersonalMemory.ReparseInfo]::ReadTag($Path)
}

function Assert-PlainPath([string]$Path) {
    $candidate=[IO.Path]::GetFullPath($Path)
    while ($candidate) {
        $item=Get-Item -LiteralPath $candidate -Force -ErrorAction SilentlyContinue
        if ($item -and ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            $tag=Get-ReparseTag $candidate
            # IO_REPARSE_TAG_CLOUD and CLOUD_1..F mark ordinary cloud-backed
            # files/directories. They do not redirect the path to another target.
            $cloudMask=[Convert]::ToUInt32('ffff0fff',16)
            $cloudTag=[Convert]::ToUInt32('9000001a',16)
            if (($tag -band $cloudMask) -ne $cloudTag) {
                throw ('Source and runtime paths must not traverse symbolic links or directory junctions. Linked path: '+$candidate)
            }
        }
        $parent=[IO.Directory]::GetParent($candidate)
        if (!$parent) { break }
        $candidate=$parent.FullName
    }
}

function Get-SourceRuntimeFiles {
    $base='server/personal-memory'
    $files=[ordered]@{}
    foreach ($name in @(
        'archive_store.py','archive_categories.py','backup_bundle.py','backup_github.py','backup_manager.py',
        'backup_server.py','device_archive.py','device_gateway.py','device_updates.py',
        'market_tools.py','mcp_admin.py','mcp_marketplace.py','mcp_observability.py',
        'mcp_packages.py','mcp_pipe.py','mcp_server.py','planner_server.py',
        'planner_store.py','planner_tools.py','restore_backup.py','runtime.py'
    )) { $files["$base/vendor/$name"]="app/$name" }
    foreach ($directory in @('mcp_admin_web','planner_web')) {
        foreach ($name in @('index.html','style.css','app.js')) {
            $files["$base/vendor/$directory/$name"]="app/$directory/$name"
        }
    }
    foreach ($name in @('launcher.py','dashboard.py','bootstrap.ps1','manage.ps1',
                        'Start.cmd','Stop.cmd','Configure.cmd','onboarding.py')) {
        $files["$base/local/$name"]=$name
    }
    foreach ($name in @('index.html','server.py','LICENSE','SOURCE.json')) {
        $files["$base/viewer/$name"]="viewer/$name"
    }
    foreach ($name in @('style.css','personal.mjs','personal-shared.mjs','personal-native.css',
                        'personal-model.mjs','favicon.svg','backup.mjs','backup.css','categories.mjs','categories.css','record-editor.mjs','record-editor.css','editor-model.mjs')) {
        $files["$base/viewer/static/$name"]="viewer/static/$name"
    }
    $files["$base/distribution/public-fonts.css"]='viewer/static/brand-fonts.css'
    $files["$base/distribution/.env.example"]='app/.env.example'
    $files["$base/requirements.txt"]='requirements.txt'
    return $files
}

function Write-NewAtomicFile([string]$Destination, [byte[]]$Bytes) {
    # Interrupted writes must never leave an apparently installed final file.
    $temporary=$Destination+'.tmp-'+[Guid]::NewGuid().ToString('N')
    Assert-PlainPath $temporary
    try {
        $stream=[IO.File]::Open($temporary,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
        try { $stream.Write($Bytes,0,$Bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
        [IO.File]::Move($temporary,$Destination)
    } finally {
        if ([IO.File]::Exists($temporary)) { [IO.File]::Delete($temporary) }
    }
}

function Assert-RuntimePaths([string]$Runtime) {
    Assert-PlainPath $Runtime
    foreach ($relative in @('runtime-install.json','process.json','dashboard-process.json',
        '.source-assembly.lock','.workspace-lifecycle.lock','.bootstrap.lock',
        '.current-lifecycle.lock','app/.env','state/data','state/launcher-processes.json',
        'state/.launcher.lock','logs/bootstrap.log','logs/dashboard.stdout.log',
        'logs/dashboard.stderr.log','logs/cloud.stdout.log','logs/cloud.stderr.log',
        '.venv/Scripts/python.exe','.venv/requirements.sha256','.tools/python','.tools/uv-cache')) {
        Assert-PlainPath (Join-Path $Runtime $relative)
    }
    foreach ($relative in (Get-SourceRuntimeFiles).Values) {
        Assert-PlainPath (Join-Path $Runtime $relative)
    }
}

function Get-SourceRuntimeKind([string]$Runtime) {
    Assert-RuntimePaths $Runtime
    $marker=Join-Path $Runtime 'runtime-install.json'
    if (Test-Path -LiteralPath $marker) {
        try { $record=Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json }
        catch { throw 'Invalid runtime-install.json. Restore the installation marker before continuing.' }
        if ($record.manager -ne 'portable' -or $record.schema -ne 1) {
            throw 'Unsupported runtime installation marker. Refusing to change this installation.'
        }
        return 'portable'
    }
    if ((Test-Path -LiteralPath (Join-Path $Runtime 'process.json')) -or
        (Test-Path -LiteralPath (Join-Path $Runtime 'dashboard-process.json'))) { return 'legacy' }
    if (Test-Path -LiteralPath (Join-Path $Runtime 'state/launcher-processes.json')) { return 'portable' }
    return 'new'
}

function Initialize-SourceRuntime([string]$SourceWorkspace) {
    $sourceRoot=[IO.Path]::GetFullPath($SourceWorkspace)
    Assert-PlainPath $sourceRoot
    if (!(Test-Path -LiteralPath $sourceRoot -PathType Container)) { throw 'Source workspace does not exist.' }
    $runtime=Join-Path $sourceRoot 'artifacts/local-memory-mcp'
    $kind=Get-SourceRuntimeKind $runtime
    if ($kind -eq 'legacy') { throw 'The existing private installation must use current_memory.ps1.' }
    $files=Get-SourceRuntimeFiles
    # Validate the entire input/output plan before creating or copying anything.
    foreach ($entry in $files.GetEnumerator()) {
        $source=Join-Path $sourceRoot $entry.Key
        Assert-PlainPath $source
        if (!(Test-Path -LiteralPath $source -PathType Leaf)) { throw ('Missing reviewed runtime source: '+$entry.Key) }
        $destination=Join-Path $runtime $entry.Value
        if ((Test-Path -LiteralPath $destination) -and !(Test-Path -LiteralPath $destination -PathType Leaf)) {
            throw ('A runtime file path is occupied by a directory: '+$entry.Value)
        }
    }
    New-Item -ItemType Directory -Path $runtime -Force | Out-Null
    $lock=$null
    try {
        $deadline=[DateTime]::UtcNow.AddSeconds(30)
        while (!$lock) {
            try { $lock=[IO.File]::Open((Join-Path $runtime '.source-assembly.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None) }
            catch [IO.IOException] {
                if ([DateTime]::UtcNow -gt $deadline) { throw 'Another source assembly is busy. Please retry.' }
                Start-Sleep -Milliseconds 100
            }
        }
        Assert-RuntimePaths $runtime
        # Installation is create-only. Repeated clicks never refresh running code,
        # configuration, databases, dependency markers or process records.
        foreach ($entry in $files.GetEnumerator()) {
            $destination=Join-Path $runtime $entry.Value
            if (Test-Path -LiteralPath $destination -PathType Leaf) { continue }
            $source=Join-Path $sourceRoot $entry.Key
            Assert-PlainPath $source
            Assert-PlainPath $destination
            New-Item -ItemType Directory -Path (Split-Path $destination -Parent) -Force | Out-Null
            $bytes=[IO.File]::ReadAllBytes($source)
            if ($entry.Value -eq 'viewer/static/style.css') {
                $css=[Text.Encoding]::UTF8.GetString($bytes)
                $css=[regex]::Replace($css,'(?im)^\s*@font-face\s*\{[^}]*\}\s*','')
                $css=$css.Replace('"Workspace Sans",','"Segoe UI Variable",')
                $bytes=[Text.UTF8Encoding]::new($false).GetBytes($css)
            }
            Write-NewAtomicFile $destination $bytes
        }
        $marker=Join-Path $runtime 'runtime-install.json'
        if (!(Test-Path -LiteralPath $marker)) {
            $json=@{schema=1;manager='portable';source='reviewed-source-allowlist';code_update='create-only'} | ConvertTo-Json
            $bytes=[Text.UTF8Encoding]::new($false).GetBytes($json+[Environment]::NewLine)
            Write-NewAtomicFile $marker $bytes
        }
    } finally { if ($lock) { $lock.Dispose() } }
    return $runtime
}

if ($MyInvocation.InvocationName -ne '.') {
    $ErrorActionPreference='Stop'
    try { Initialize-SourceRuntime $Workspace }
    catch { [Console]::Error.WriteLine('Source runtime: '+$_.Exception.Message); exit 1 }
}
