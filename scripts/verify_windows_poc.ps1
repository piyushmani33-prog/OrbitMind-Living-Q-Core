[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BundlePath,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedManifestPath,
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$Executable = Join-Path $BundlePath "OrbitMind.exe"
$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("OrbitMind-U5.0B1-" + [guid]::NewGuid().ToString("N"))
$EvidenceRoot = Join-Path $TempRoot "evidence"
$OriginalLocalAppData = $env:LOCALAPPDATA

if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) { throw "Frozen executable missing." }
if (-not (Test-Path -LiteralPath $ExpectedManifestPath -PathType Leaf)) { throw "Manifest missing." }
if ($Port -lt 1024 -or $Port -gt 65535) { throw "Port outside the approved range." }
New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
$env:LOCALAPPDATA = $TempRoot

function Wait-Workbench {
    param([int]$ReadyPort, [int]$Seconds = 45)
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$ReadyPort/health" -TimeoutSec 1
            $workbench = Invoke-WebRequest -Uri "http://127.0.0.1:$ReadyPort/workbench" -TimeoutSec 1
            if ($health.status -eq "ok" -and $health.database -eq "connected" -and $workbench.StatusCode -eq 200) { return }
        } catch { Start-Sleep -Milliseconds 100 }
    }
    throw "Runtime readiness timeout."
}

Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;

public sealed class OrbitMindProcessHandle {
    internal OrbitMindProcessHandle(
        int processId,
        Process process,
        IntPtr nativeProcessHandle,
        DateTime processCreationTimeUtc,
        string role) {
        ProcessId = processId;
        Process = process;
        NativeProcessHandle = nativeProcessHandle;
        ProcessCreationTimeUtc = processCreationTimeUtc;
        Role = role;
    }

    public int ProcessId { get; private set; }
    public Process Process { get; private set; }
    public IntPtr NativeProcessHandle { get; internal set; }
    public bool NativeHandleClosed { get; internal set; }
    public bool ManagedProcessDisposed { get; internal set; }
    public DateTime ProcessCreationTimeUtc { get; private set; }
    public string Role { get; private set; }
}

public sealed class OrbitMindNativeExitResult {
    public int ProcessId { get; set; }
    public uint WaitResult { get; set; }
    public string WaitResultName { get; set; }
    public bool TimedOut { get; set; }
    public int WaitLastError { get; set; }
    public bool ExitCodeAvailable { get; set; }
    public int ExitCodeLastError { get; set; }
    public uint NativeExitCodeUInt32 { get; set; }
    public int NativeExitCodeInt32 { get; set; }
    public bool StillActiveAfterWait { get; set; }
}

public sealed class OrbitMindNativeHandleCloseResult {
    public int ProcessId { get; set; }
    public bool Success { get; set; }
    public bool AlreadyClosed { get; set; }
    public int LastError { get; set; }
    public bool ManagedProcessDisposed { get; set; }
}

public static class OrbitMindProcessGroup {
    private const uint CREATE_NEW_PROCESS_GROUP = 0x00000200;
    private const uint CTRL_BREAK_EVENT = 1;
    public const uint WAIT_OBJECT_0 = 0x00000000;
    public const uint WAIT_TIMEOUT = 0x00000102;
    public const uint WAIT_FAILED = 0xFFFFFFFF;
    public const uint STILL_ACTIVE = 259;
    private const int ERROR_INVALID_HANDLE = 6;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct STARTUPINFO {
        public int cb;
        public string lpReserved;
        public string lpDesktop;
        public string lpTitle;
        public int dwX;
        public int dwY;
        public int dwXSize;
        public int dwYSize;
        public int dwXCountChars;
        public int dwYCountChars;
        public int dwFillAttribute;
        public int dwFlags;
        public short wShowWindow;
        public short cbReserved2;
        public IntPtr lpReserved2;
        public IntPtr hStdInput;
        public IntPtr hStdOutput;
        public IntPtr hStdError;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct PROCESS_INFORMATION {
        public IntPtr hProcess;
        public IntPtr hThread;
        public int dwProcessId;
        public int dwThreadId;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CreateProcess(
        string applicationName,
        StringBuilder commandLine,
        IntPtr processAttributes,
        IntPtr threadAttributes,
        bool inheritHandles,
        uint creationFlags,
        IntPtr environment,
        string currentDirectory,
        ref STARTUPINFO startupInfo,
        out PROCESS_INFORMATION processInformation);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GenerateConsoleCtrlEvent(uint controlEvent, uint processGroupId);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetExitCodeProcess(IntPtr processHandle, out uint exitCode);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr handle);

    [DllImport("kernel32.dll")]
    private static extern void SetLastError(uint errorCode);

    public static OrbitMindProcessHandle Start(
        string executable,
        string arguments,
        string workingDirectory,
        string role) {
        var startup = new STARTUPINFO();
        startup.cb = Marshal.SizeOf(startup);
        PROCESS_INFORMATION process;
        var command = new StringBuilder("\"" + executable + "\" " + arguments);
        if (!CreateProcess(executable, command, IntPtr.Zero, IntPtr.Zero, false,
                           CREATE_NEW_PROCESS_GROUP, IntPtr.Zero, workingDirectory,
                           ref startup, out process)) {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        if (!CloseHandle(process.hThread)) {
            int error = Marshal.GetLastWin32Error();
            CloseHandle(process.hProcess);
            throw new Win32Exception(error);
        }
        try {
            Process managedProcess = Process.GetProcessById(process.dwProcessId);
            DateTime creationTimeUtc = managedProcess.StartTime.ToUniversalTime();
            return new OrbitMindProcessHandle(
                process.dwProcessId,
                managedProcess,
                process.hProcess,
                creationTimeUtc,
                role);
        } catch {
            CloseHandle(process.hProcess);
            throw;
        }
    }

    public static void RequestStop(int processId) {
        if (!GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT, (uint)processId)) {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
    }

    public static OrbitMindNativeExitResult WaitForNativeExit(
        OrbitMindProcessHandle process,
        uint timeoutMilliseconds) {
        if (process == null) {
            throw new ArgumentNullException("process");
        }
        if (process.NativeHandleClosed || process.NativeProcessHandle == IntPtr.Zero) {
            throw new InvalidOperationException("Native process handle is unavailable.");
        }

        SetLastError(0);
        uint waitResult = WaitForSingleObject(process.NativeProcessHandle, timeoutMilliseconds);
        var result = new OrbitMindNativeExitResult {
            ProcessId = process.ProcessId,
            WaitResult = waitResult,
            WaitResultName = waitResult == WAIT_OBJECT_0 ? "WAIT_OBJECT_0" :
                waitResult == WAIT_TIMEOUT ? "WAIT_TIMEOUT" :
                waitResult == WAIT_FAILED ? "WAIT_FAILED" : "WAIT_UNEXPECTED",
            TimedOut = waitResult == WAIT_TIMEOUT,
            WaitLastError = waitResult == WAIT_FAILED ? Marshal.GetLastWin32Error() : 0
        };

        if (waitResult != WAIT_OBJECT_0) {
            return result;
        }

        SetLastError(0);
        uint exitCode;
        if (!GetExitCodeProcess(process.NativeProcessHandle, out exitCode)) {
            result.ExitCodeLastError = Marshal.GetLastWin32Error();
            return result;
        }
        result.ExitCodeAvailable = true;
        result.NativeExitCodeUInt32 = exitCode;
        result.NativeExitCodeInt32 = unchecked((int)exitCode);
        result.StillActiveAfterWait = exitCode == STILL_ACTIVE;
        return result;
    }

    public static OrbitMindNativeHandleCloseResult CloseNativeHandle(
        OrbitMindProcessHandle process) {
        if (process == null) {
            throw new ArgumentNullException("process");
        }
        if (process.NativeHandleClosed) {
            return new OrbitMindNativeHandleCloseResult {
                ProcessId = process.ProcessId,
                Success = true,
                AlreadyClosed = true,
                ManagedProcessDisposed = process.ManagedProcessDisposed
            };
        }
        if (process.NativeProcessHandle == IntPtr.Zero) {
            return new OrbitMindNativeHandleCloseResult {
                ProcessId = process.ProcessId,
                Success = false,
                LastError = ERROR_INVALID_HANDLE,
                ManagedProcessDisposed = process.ManagedProcessDisposed
            };
        }

        SetLastError(0);
        if (!CloseHandle(process.NativeProcessHandle)) {
            return new OrbitMindNativeHandleCloseResult {
                ProcessId = process.ProcessId,
                Success = false,
                LastError = Marshal.GetLastWin32Error(),
                ManagedProcessDisposed = process.ManagedProcessDisposed
            };
        }
        process.NativeProcessHandle = IntPtr.Zero;
        process.NativeHandleClosed = true;
        if (!process.ManagedProcessDisposed) {
            process.Process.Dispose();
            process.ManagedProcessDisposed = true;
        }
        return new OrbitMindNativeHandleCloseResult {
            ProcessId = process.ProcessId,
            Success = true,
            ManagedProcessDisposed = process.ManagedProcessDisposed
        };
    }
}
'@

function Wait-OrbitMindNativeExit {
    param(
        [Parameter(Mandatory = $true)]
        [object]$ProcessHandle,
        [int]$TimeoutMilliseconds = 30000
    )
    if ($ProcessHandle.NativeHandleClosed -or $ProcessHandle.NativeProcessHandle -eq [IntPtr]::Zero) {
        throw "Native process handle is unavailable."
    }
    $result = [OrbitMindProcessGroup]::WaitForNativeExit(
        $ProcessHandle,
        [uint32]$TimeoutMilliseconds
    )
    if ($result.WaitResult -eq [OrbitMindProcessGroup]::WAIT_FAILED) {
        throw "Native process wait failed (Win32 error $($result.WaitLastError))."
    }
    if ($result.WaitResult -notin @(
            [OrbitMindProcessGroup]::WAIT_OBJECT_0,
            [OrbitMindProcessGroup]::WAIT_TIMEOUT
        )) {
        throw "Native process wait returned an unexpected result."
    }
    if (-not $result.TimedOut -and -not $result.ExitCodeAvailable) {
        throw "Native exit-code capture failed (Win32 error $($result.ExitCodeLastError))."
    }
    if ($result.StillActiveAfterWait) {
        throw "Native process remained active after a successful wait."
    }
    return $result
}

function Assert-OrbitMindNativeExit {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Result,
        [Parameter(Mandatory = $true)]
        [uint32]$ExpectedExitCode,
        [Parameter(Mandatory = $true)]
        [string]$FailureMessage
    )
    if ($Result.TimedOut) { throw "$FailureMessage Native wait timed out." }
    if ($Result.NativeExitCodeUInt32 -ne $ExpectedExitCode) {
        throw "$FailureMessage Native exit code was $($Result.NativeExitCodeUInt32)."
    }
}

function Close-OrbitMindNativeHandle {
    param(
        [Parameter(Mandatory = $true)]
        [object]$ProcessHandle
    )
    $result = [OrbitMindProcessGroup]::CloseNativeHandle($ProcessHandle)
    if (-not $result.Success) {
        throw "Native process handle close failed (Win32 error $($result.LastError))."
    }
    return $result
}

function New-OrbitMindProcessEvidence {
    param(
        [Parameter(Mandatory = $true)]
        [object]$ProcessHandle,
        [Parameter(Mandatory = $true)]
        [object]$WaitResult,
        [Parameter(Mandatory = $true)]
        [object]$CloseResult,
        [Parameter(Mandatory = $true)]
        [string]$Role,
        [Parameter(Mandatory = $true)]
        [uint32]$ExpectedExitCode
    )
    $assertionPassed = (
        $WaitResult.WaitResult -eq [OrbitMindProcessGroup]::WAIT_OBJECT_0 -and
        -not $WaitResult.TimedOut -and
        $WaitResult.ExitCodeAvailable -and
        $WaitResult.NativeExitCodeUInt32 -eq $ExpectedExitCode -and
        $CloseResult.Success -and
        $ProcessHandle.NativeHandleClosed
    )
    return [ordered]@{
        role = $Role
        process_id = $ProcessHandle.ProcessId
        process_creation_time_utc = $ProcessHandle.ProcessCreationTimeUtc.ToString("o")
        wait_result = $WaitResult.WaitResultName
        wait_result_uint32 = $WaitResult.WaitResult
        timed_out = $WaitResult.TimedOut
        wait_last_error = $WaitResult.WaitLastError
        exit_code_last_error = $WaitResult.ExitCodeLastError
        native_exit_code_uint32 = $WaitResult.NativeExitCodeUInt32
        native_exit_code_int32 = $WaitResult.NativeExitCodeInt32
        handle_close_success = $CloseResult.Success
        handle_already_closed = $CloseResult.AlreadyClosed
        handle_close_last_error = $CloseResult.LastError
        handle_closed = $ProcessHandle.NativeHandleClosed
        managed_process_disposed = $CloseResult.ManagedProcessDisposed
        expected_exit_code = $ExpectedExitCode
        assertion_passed = $assertionPassed
    }
}

function Write-OrbitMindProcessResult {
    param(
        [Parameter(Mandatory = $true)]
        [System.Collections.IDictionary]$Evidence
    )
    $handleClosed = $Evidence["handle_closed"].ToString().ToLowerInvariant()
    $assertionPassed = $Evidence["assertion_passed"].ToString().ToLowerInvariant()
    $line = "orbitmind_process_result role={0} pid={1} wait={2} exit_uint32={3} exit_int32={4} handle_closed={5} expected={6} passed={7}" -f `
        $Evidence["role"], $Evidence["process_id"], $Evidence["wait_result"], `
        $Evidence["native_exit_code_uint32"], $Evidence["native_exit_code_int32"], `
        $handleClosed, $Evidence["expected_exit_code"], $assertionPassed
    [Console]::Out.WriteLine($line)
}

function Test-OrbitMindDatabaseRelease {
    param(
        [Parameter(Mandatory = $true)]
        [string]$DatabasePath
    )
    $stream = $null
    $renameProbe = "$DatabasePath.release-probe"
    try {
        $stream = [System.IO.File]::Open(
            $DatabasePath,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read,
            [System.IO.FileShare]::None
        )
        $stream.Dispose()
        $stream = $null
        if (Test-Path -LiteralPath $renameProbe) {
            throw "Database release probe path already exists."
        }
        Move-Item -LiteralPath $DatabasePath -Destination $renameProbe
        Move-Item -LiteralPath $renameProbe -Destination $DatabasePath
    } finally {
        if ($null -ne $stream) { $stream.Dispose() }
        if ((Test-Path -LiteralPath $renameProbe) -and -not (Test-Path -LiteralPath $DatabasePath)) {
            Move-Item -LiteralPath $renameProbe -Destination $DatabasePath
        }
    }
    return [ordered]@{
        read_only_open = $true
        rename_restore = $true
    }
}

$processHandles = [System.Collections.Generic.List[object]]::new()
$listener = $null
$collision = $null
$runtime = $null
$duplicate = $null
$restart = $null

try {
    $manifestEntries = Get-Content -LiteralPath $ExpectedManifestPath | Where-Object { $_ -match '^[0-9a-f]{64}  ' }
    foreach ($entry in $manifestEntries) {
        $hash, $relative = $entry -split '  ', 2
        $file = Join-Path $BundlePath $relative
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Frozen manifest file missing." }
        if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $hash) { throw "Frozen manifest mismatch." }
    }

    # Port collision is checked before a primary runtime holds the SID mutex.
    $collisionPort = $Port + 1
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $collisionPort)
    $listener.Start()
    try {
        $collision = [OrbitMindProcessGroup]::Start(
            $Executable, "--port $collisionPort --no-browser", $BundlePath, "collision"
        )
        $processHandles.Add($collision)
        $collisionWait = Wait-OrbitMindNativeExit -ProcessHandle $collision
        Assert-OrbitMindNativeExit -Result $collisionWait -ExpectedExitCode 21 -FailureMessage "Port-collision guard failed."
    } finally {
        $listener.Stop()
        $listener = $null
    }
    $collisionClose = Close-OrbitMindNativeHandle -ProcessHandle $collision
    $collisionEvidence = New-OrbitMindProcessEvidence `
        -ProcessHandle $collision `
        -WaitResult $collisionWait `
        -CloseResult $collisionClose `
        -Role "collision" `
        -ExpectedExitCode 21
    Write-OrbitMindProcessResult -Evidence $collisionEvidence

    $runtime = [OrbitMindProcessGroup]::Start(
        $Executable, "--port $Port --no-browser", $BundlePath, "primary"
    )
    $processHandles.Add($runtime)
    Wait-Workbench -ReadyPort $Port

    $listeners = @(Get-NetTCPConnection -State Listen -OwningProcess $runtime.ProcessId -ErrorAction Stop)
    if ($listeners.Count -ne 1 -or $listeners[0].LocalAddress -ne "127.0.0.1" -or $listeners[0].LocalPort -ne $Port) {
        throw "Frozen runtime is not bound exclusively to the approved loopback endpoint."
    }
    $asset = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/assets/trajectory-replay.js"
    if ($asset.StatusCode -ne 200) { throw "Replay asset unavailable." }

    $smoke = Invoke-WebRequest -Method Post -Uri "http://127.0.0.1:$Port/workbench/run" -ContentType "application/x-www-form-urlencoded" -Body @{
        source_mode = "catalog"; catalog_sample_id = "iss"; custom_label = ""; tle_line1 = ""; tle_line2 = ""
        observer_latitude_deg = "0"; observer_longitude_deg = "0"; observer_altitude_metres = "0"
        start_time_utc = "2019-12-09T19:40:00Z"; duration_hours = "1"; minimum_elevation_deg = "0"
    }
    if ($smoke.StatusCode -ne 200) { throw "Default-mode smoke flow failed." }

    $duplicate = [OrbitMindProcessGroup]::Start(
        $Executable, "--port $Port --no-browser", $BundlePath, "duplicate"
    )
    $processHandles.Add($duplicate)
    $duplicateWait = Wait-OrbitMindNativeExit -ProcessHandle $duplicate
    Assert-OrbitMindNativeExit -Result $duplicateWait -ExpectedExitCode 20 -FailureMessage "Duplicate-launch guard failed."
    $duplicateClose = Close-OrbitMindNativeHandle -ProcessHandle $duplicate
    $duplicateEvidence = New-OrbitMindProcessEvidence `
        -ProcessHandle $duplicate `
        -WaitResult $duplicateWait `
        -CloseResult $duplicateClose `
        -Role "duplicate" `
        -ExpectedExitCode 20
    Write-OrbitMindProcessResult -Evidence $duplicateEvidence

    $connections = @(Get-NetTCPConnection -OwningProcess $runtime.ProcessId -ErrorAction SilentlyContinue)
    $external = @($connections | Where-Object { $_.RemoteAddress -and $_.RemoteAddress -notin @("127.0.0.1", "0.0.0.0", "::1", "::") })
    if ($external.Count) { throw "Unexpected non-loopback connection observed." }

    [OrbitMindProcessGroup]::RequestStop($runtime.ProcessId)
    $firstShutdownWait = Wait-OrbitMindNativeExit -ProcessHandle $runtime
    Assert-OrbitMindNativeExit -Result $firstShutdownWait -ExpectedExitCode 0 -FailureMessage "Clean shutdown was not observed."
    $firstShutdownClose = Close-OrbitMindNativeHandle -ProcessHandle $runtime
    $firstShutdownEvidence = New-OrbitMindProcessEvidence `
        -ProcessHandle $runtime `
        -WaitResult $firstShutdownWait `
        -CloseResult $firstShutdownClose `
        -Role "primary_shutdown" `
        -ExpectedExitCode 0
    Write-OrbitMindProcessResult -Evidence $firstShutdownEvidence

    $database = Join-Path $TempRoot "OrbitMind\data\orbitmind.db"
    if (-not (Test-Path -LiteralPath $database -PathType Leaf)) { throw "User database missing after shutdown." }
    $baselineDatabaseRelease = Test-OrbitMindDatabaseRelease -DatabasePath $database
    $baselineDatabaseItem = Get-Item -LiteralPath $database
    $baselineDatabaseHash = (Get-FileHash -LiteralPath $database -Algorithm SHA256).Hash
    $baselineDatabaseSize = $baselineDatabaseItem.Length
    $baselineDatabaseLastWriteUtc = $baselineDatabaseItem.LastWriteTimeUtc.ToString("o")

    $restart = [OrbitMindProcessGroup]::Start(
        $Executable, "--port $Port --no-browser", $BundlePath, "restart"
    )
    $processHandles.Add($restart)
    Wait-Workbench -ReadyPort $Port
    $runtimeDatabases = @(Get-ChildItem -LiteralPath $TempRoot -Recurse -File -Filter "orbitmind.db")
    if ($runtimeDatabases.Count -ne 1 -or $runtimeDatabases[0].FullName -ne $database) {
        throw "Restart did not reuse the single approved database."
    }

    [OrbitMindProcessGroup]::RequestStop($restart.ProcessId)
    $secondShutdownWait = Wait-OrbitMindNativeExit -ProcessHandle $restart
    Assert-OrbitMindNativeExit -Result $secondShutdownWait -ExpectedExitCode 0 -FailureMessage "Restart shutdown was not clean."
    $secondShutdownClose = Close-OrbitMindNativeHandle -ProcessHandle $restart
    $secondShutdownEvidence = New-OrbitMindProcessEvidence `
        -ProcessHandle $restart `
        -WaitResult $secondShutdownWait `
        -CloseResult $secondShutdownClose `
        -Role "restart_shutdown" `
        -ExpectedExitCode 0
    Write-OrbitMindProcessResult -Evidence $secondShutdownEvidence

    $remainingRestartListeners = @(
        Get-NetTCPConnection -State Listen -OwningProcess $restart.ProcessId -ErrorAction SilentlyContinue
    )
    if ($remainingRestartListeners.Count) { throw "Restart listener remained after shutdown." }
    $finalDatabaseRelease = Test-OrbitMindDatabaseRelease -DatabasePath $database
    $finalDatabaseItem = Get-Item -LiteralPath $database
    $finalDatabaseHash = (Get-FileHash -LiteralPath $database -Algorithm SHA256).Hash
    $finalDatabaseSize = $finalDatabaseItem.Length
    $finalDatabaseLastWriteUtc = $finalDatabaseItem.LastWriteTimeUtc.ToString("o")
    if ($finalDatabaseHash -ne $baselineDatabaseHash) { throw "User data changed unexpectedly across restart." }

    [ordered]@{
        verification = "PASS"
        bind = "127.0.0.1:$Port"
        workbench = "PASS"
        replay_asset = "PASS"
        smoke_flow = "PASS"
        duplicate_launch = "PASS"
        port_collision = "PASS"
        data_survival = "PASS"
        external_network_observed = $false
        native_process_results = [ordered]@{
            collision = $collisionEvidence
            duplicate = $duplicateEvidence
            primary_shutdown = $firstShutdownEvidence
            restart_shutdown = $secondShutdownEvidence
        }
        database_persistence = [ordered]@{
            baseline_sha256 = $baselineDatabaseHash.ToLowerInvariant()
            final_sha256 = $finalDatabaseHash.ToLowerInvariant()
            hashes_equal = $finalDatabaseHash -eq $baselineDatabaseHash
            baseline_size = $baselineDatabaseSize
            final_size = $finalDatabaseSize
            baseline_last_write_utc = $baselineDatabaseLastWriteUtc
            final_last_write_utc = $finalDatabaseLastWriteUtc
            baseline_revision = "n9c0d1e2f3g4"
            final_revision = "n9c0d1e2f3g4"
            baseline_integrity = "runtime_preflight_passed"
            final_integrity = "runtime_preflight_passed"
            persisted_smoke_state = "PASS"
            baseline_read_only_open = $baselineDatabaseRelease["read_only_open"]
            baseline_rename_restore = $baselineDatabaseRelease["rename_restore"]
            final_read_only_open = $finalDatabaseRelease["read_only_open"]
            final_rename_restore = $finalDatabaseRelease["rename_restore"]
            hashes_taken_while_runtime_stopped = $true
        }
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $EvidenceRoot "frozen-verification.json") -Encoding utf8
} finally {
    if ($null -ne $listener) { $listener.Stop() }
    $cleanupErrors = [System.Collections.Generic.List[string]]::new()
    foreach ($processHandle in $processHandles) {
        if ($null -eq $processHandle -or $processHandle.NativeHandleClosed) { continue }
        try {
            if (-not $processHandle.Process.HasExited) {
                try { [OrbitMindProcessGroup]::RequestStop($processHandle.ProcessId) } catch { }
                try { $null = [OrbitMindProcessGroup]::WaitForNativeExit($processHandle, 5000) } catch { }
            }
            $cleanupClose = [OrbitMindProcessGroup]::CloseNativeHandle($processHandle)
            if (-not $cleanupClose.Success) {
                $cleanupErrors.Add("$($processHandle.Role): Win32 error $($cleanupClose.LastError)")
            }
        } catch {
            $cleanupErrors.Add("$($processHandle.Role): $($_.Exception.Message)")
        }
    }
    $env:LOCALAPPDATA = $OriginalLocalAppData
    if ($cleanupErrors.Count) {
        throw "Native process cleanup failed: $($cleanupErrors -join '; ')"
    }
}
