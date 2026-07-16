[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PythonExe,
    [Parameter(Mandatory = $true)]
    [string]$WheelhousePath,
    [Parameter(Mandatory = $true)]
    [string]$ExternalBuildRoot
)

$ErrorActionPreference = "Stop"
$ExpectedLockHash = "785d303155e2ee03915b17d5d5f9a24f009d087465af2b1d9355de2ac0c4102c"
$ExpectedPython = "3.12.10"
$ExpectedWheelCount = 48
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LockPath = Join-Path $RepositoryRoot "requirements\u5.0b0-windows-py312.lock.txt"
$SpecPath = Join-Path $RepositoryRoot "packaging\orbitmind.spec"

function Get-CanonicalPath {
    param(
        [string]$Path,
        [string]$Label
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "$Label must be a nonempty absolute Windows path."
    }
    $windowsPath = $Path.Replace('/', '\')
    if ($windowsPath.StartsWith('\\?\') -or $windowsPath.StartsWith('\\.\')) {
        throw "$Label must not use a Windows device-path prefix."
    }
    if ($windowsPath -match '(^|[\\])[.]{1,2}($|[\\])') {
        throw "$Label must not contain relative path segments."
    }
    if (($windowsPath -match '[. ]($|[\\])') -or
        ($windowsPath -match '(^|[\\])[^\\]*~[0-9]+[^\\]*($|[\\])')) {
        throw "$Label must not use an ambiguous or short-name path spelling."
    }
    if ($windowsPath -notmatch '^(?:[A-Za-z]:[\\]|[\\]{2}[^\\]+[\\][^\\]+)') {
        throw "$Label must be a fully qualified Windows path."
    }
    try {
        $fullPath = [System.IO.Path]::GetFullPath($windowsPath)
    }
    catch {
        throw "$Label is not a valid Windows path."
    }
    return $fullPath.TrimEnd([char[]]@('\', '/'))
}

function Test-PathEqual {
    param(
        [string]$Left,
        [string]$Right
    )

    return [string]::Equals($Left, $Right, [System.StringComparison]::OrdinalIgnoreCase)
}

function Test-StrictDescendant {
    param(
        [string]$Parent,
        [string]$Child
    )

    if (Test-PathEqual -Left $Parent -Right $Child) { return $false }
    $prefix = $Parent.TrimEnd('\') + '\'
    return $Child.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)
}

function Assert-NoReparsePoint {
    param(
        [string]$Path,
        [string]$Label
    )

    if (Test-Path -LiteralPath $Path) {
        $item = Get-Item -LiteralPath $Path -Force
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "$Label must not be a reparse point or symbolic link."
        }
    }
}

function Assert-ExternalBuildRoot {
    param(
        [string]$Path,
        [string]$Repository,
        [string]$Wheelhouse,
        [string[]]$ProtectedPaths
    )

    $external = Get-CanonicalPath -Path $Path -Label "ExternalBuildRoot"
    $pathRoot = [System.IO.Path]::GetPathRoot($external).TrimEnd([char[]]@('\', '/'))
    if (Test-PathEqual -Left $external -Right $pathRoot) {
        throw "ExternalBuildRoot must not be a drive or share root."
    }

    $userProfile = Get-CanonicalPath -Path ([Environment]::GetFolderPath("UserProfile")) -Label "User profile"
    $localAppData = Get-CanonicalPath -Path ([Environment]::GetFolderPath("LocalApplicationData")) -Label "LocalAppData"
    if ((Test-PathEqual -Left $external -Right $userProfile) -or
        (Test-PathEqual -Left $external -Right $localAppData)) {
        throw "ExternalBuildRoot must not be a user-profile or LocalAppData root."
    }

    if ((Test-PathEqual -Left $external -Right $Repository) -or
        (Test-StrictDescendant -Parent $Repository -Child $external)) {
        throw "ExternalBuildRoot must be outside the repository."
    }
    if ((Test-PathEqual -Left $external -Right $Wheelhouse) -or
        (Test-StrictDescendant -Parent $Wheelhouse -Child $external)) {
        throw "ExternalBuildRoot must be outside the approved wheelhouse."
    }
    foreach ($protected in $ProtectedPaths) {
        if ((Test-PathEqual -Left $external -Right $protected) -or
            (Test-StrictDescendant -Parent $external -Child $protected) -or
            (Test-StrictDescendant -Parent $protected -Child $external)) {
            throw "ExternalBuildRoot overlaps a protected historical path."
        }
    }
    Assert-NoReparsePoint -Path $external -Label "ExternalBuildRoot"
    return $external
}

function Assert-SafeExternalChildPath {
    param(
        [string]$ExternalRoot,
        [string]$Path,
        [string]$ExpectedLeaf,
        [string[]]$ProtectedPaths
    )

    $child = Get-CanonicalPath -Path $Path -Label $ExpectedLeaf
    if (-not (Test-StrictDescendant -Parent $ExternalRoot -Child $child)) {
        throw "$ExpectedLeaf must be a strict descendant of ExternalBuildRoot."
    }
    if (-not [string]::Equals(
        [System.IO.Path]::GetFileName($child),
        $ExpectedLeaf,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Generated path has an unexpected leaf name."
    }
    foreach ($protected in $ProtectedPaths) {
        if ((Test-PathEqual -Left $child -Right $protected) -or
            (Test-StrictDescendant -Parent $child -Child $protected) -or
            (Test-StrictDescendant -Parent $protected -Child $child)) {
            throw "Generated path overlaps a protected historical path."
        }
    }
    Assert-NoReparsePoint -Path $ExternalRoot -Label "ExternalBuildRoot"
    Assert-NoReparsePoint -Path $child -Label $ExpectedLeaf
    return $child
}

$RepositoryRoot = Get-CanonicalPath -Path $RepositoryRoot -Label "Repository root"
$WheelhouseRoot = Get-CanonicalPath -Path $WheelhousePath -Label "WheelhousePath"
$HistoricalBuildPath = Get-CanonicalPath -Path (Join-Path $RepositoryRoot "build\u5.0b1") -Label "Historical build path"
$HistoricalDistPath = Get-CanonicalPath -Path (Join-Path $RepositoryRoot "dist\u5.0b1") -Label "Historical dist path"
$HistoricalCandidatePath = Get-CanonicalPath -Path (Join-Path $HistoricalDistPath "OrbitMind") -Label "Historical candidate path"
$LocalAppDataRoot = Get-CanonicalPath -Path ([Environment]::GetFolderPath("LocalApplicationData")) -Label "LocalAppData"
$HistoricalInstallerRoot = Get-CanonicalPath -Path (Join-Path $LocalAppDataRoot "OrbitMindBuild\U5.0I0") -Label "Historical installer workspace"
$ProtectedPaths = @(
    $RepositoryRoot,
    $HistoricalBuildPath,
    $HistoricalDistPath,
    $HistoricalCandidatePath,
    $HistoricalInstallerRoot
)
$ExternalRoot = Assert-ExternalBuildRoot `
    -Path $ExternalBuildRoot `
    -Repository $RepositoryRoot `
    -Wheelhouse $WheelhouseRoot `
    -ProtectedPaths $ProtectedPaths
$BuildVenv = Assert-SafeExternalChildPath `
    -ExternalRoot $ExternalRoot `
    -Path (Join-Path $ExternalRoot ".venv-build-offline") `
    -ExpectedLeaf ".venv-build-offline" `
    -ProtectedPaths $ProtectedPaths
$BuildPath = Assert-SafeExternalChildPath `
    -ExternalRoot $ExternalRoot `
    -Path (Join-Path $ExternalRoot "build") `
    -ExpectedLeaf "build" `
    -ProtectedPaths $ProtectedPaths
$DistPath = Assert-SafeExternalChildPath `
    -ExternalRoot $ExternalRoot `
    -Path (Join-Path $ExternalRoot "candidate") `
    -ExpectedLeaf "candidate" `
    -ProtectedPaths $ProtectedPaths
$EvidencePath = Assert-SafeExternalChildPath `
    -ExternalRoot $ExternalRoot `
    -Path (Join-Path $ExternalRoot "evidence") `
    -ExpectedLeaf "evidence" `
    -ProtectedPaths $ProtectedPaths
$LogDirectory = Assert-SafeExternalChildPath `
    -ExternalRoot $ExternalRoot `
    -Path (Join-Path $ExternalRoot "logs") `
    -ExpectedLeaf "logs" `
    -ProtectedPaths $ProtectedPaths
$LogPath = Join-Path $LogDirectory "frozen-build.log"

if ((Test-PathEqual -Left $BuildVenv -Right $BuildPath) -or
    (Test-PathEqual -Left $BuildVenv -Right $DistPath) -or
    (Test-PathEqual -Left $BuildPath -Right $DistPath) -or
    (Test-StrictDescendant -Parent $BuildPath -Child $DistPath) -or
    (Test-StrictDescendant -Parent $DistPath -Child $BuildPath)) {
    throw "Generated packaging paths must be distinct and non-overlapping."
}

if ($env:OS -ne "Windows_NT" -or $env:PROCESSOR_ARCHITECTURE -notin @("AMD64", "x86_64")) {
    throw "Windows AMD64 is required."
}
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) { throw "Python executable missing." }
$pythonVersion = (& $PythonExe -c "import platform; print(platform.python_version())").Trim()
if ($pythonVersion -ne $ExpectedPython) { throw "Python 3.12.10 is required." }
if ((Get-FileHash -LiteralPath $LockPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedLockHash) {
    throw "Approved lock identity mismatch."
}

$wheels = @(Get-ChildItem -LiteralPath $WheelhouseRoot -File -Filter "*.whl")
if ($wheels.Count -ne $ExpectedWheelCount) { throw "Approved wheelhouse must contain 48 wheels." }
if (@(Get-ChildItem -LiteralPath $WheelhouseRoot -File | Where-Object Extension -ne ".whl").Count) {
    throw "Wheelhouse contains a non-wheel file."
}
$lockText = Get-Content -LiteralPath $LockPath -Raw
$lockHashes = @([regex]::Matches($lockText, '--hash=sha256:([0-9a-f]{64})') | ForEach-Object { $_.Groups[1].Value } | Sort-Object)
$wheelHashes = @($wheels | ForEach-Object { (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() } | Sort-Object)
if ($lockHashes.Count -ne $ExpectedWheelCount -or (Compare-Object $lockHashes $wheelHashes)) {
    throw "Wheelhouse hashes do not exactly match the approved lock."
}

foreach ($generated in @(
    @{ Path = $BuildVenv; Leaf = ".venv-build-offline" },
    @{ Path = $BuildPath; Leaf = "build" },
    @{ Path = $DistPath; Leaf = "candidate" }
)) {
    $safePath = Assert-SafeExternalChildPath `
        -ExternalRoot $ExternalRoot `
        -Path $generated.Path `
        -ExpectedLeaf $generated.Leaf `
        -ProtectedPaths $ProtectedPaths
    if (Test-Path -LiteralPath $safePath) {
        Remove-Item -LiteralPath $safePath -Recurse -Force
    }
}
New-Item -ItemType Directory -Force -Path $EvidencePath, $LogDirectory | Out-Null

& $PythonExe -m venv $BuildVenv
$venvPython = Join-Path $BuildVenv "Scripts\python.exe"
$env:PIP_NO_INDEX = "1"
$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"
$env:PIP_NO_CACHE_DIR = "1"
$env:PIP_REQUIRE_VIRTUALENV = "1"

$installArgs = @(
    "-m", "pip", "install", "--no-index", "--find-links", $WheelhouseRoot,
    "--require-hashes", "--no-deps", "--no-cache-dir", "-r", $LockPath
)
& $venvPython @installArgs *>&1 | Tee-Object -FilePath $LogPath
if ($LASTEXITCODE -ne 0) { throw "Offline dependency installation failed." }

$gitSha = (git -C $RepositoryRoot rev-parse HEAD).Trim()
$gitStatus = @(git -C $RepositoryRoot status --short)
$metadata = [ordered]@{
    git_sha = $gitSha
    git_dirty = ($gitStatus.Count -ne 0)
    python = (& $venvPython --version 2>&1).Trim()
    pyinstaller = (& $venvPython -m PyInstaller --version).Trim()
    hooks = (& $venvPython -c "from importlib.metadata import version; print(version('pyinstaller-hooks-contrib'))").Trim()
    lock_sha256 = $ExpectedLockHash
    dependency_inventory = (& $venvPython -m pip list --format=json | ConvertFrom-Json)
    spec = "packaging/orbitmind.spec"
    command = "$venvPython -m PyInstaller --noconfirm --clean --workpath $BuildPath --distpath $DistPath $SpecPath"
    network_mode = "NO-INDEX"
}
$metadata | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $EvidencePath "build-metadata.json") -Encoding utf8

$required = @(
    "alembic.ini",
    "migrations\env.py",
    "migrations\script.py.mako",
    "src\orbitmind\api\assets\trajectory_replay.js"
)
foreach ($relative in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $RepositoryRoot $relative) -PathType Leaf)) {
        throw "Required package data is absent."
    }
}

# This is the only build invocation. Running this script requires a separate approval.
& $venvPython -m PyInstaller --noconfirm --clean --workpath $BuildPath --distpath $DistPath $SpecPath *>&1 |
    Tee-Object -FilePath $LogPath -Append
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

$BundlePath = Join-Path $DistPath "OrbitMind"
if (-not (Test-Path -LiteralPath (Join-Path $BundlePath "OrbitMind.exe") -PathType Leaf)) {
    throw "Expected one-folder bundle is absent."
}
Get-ChildItem -LiteralPath $BundlePath -File -Recurse | Sort-Object FullName | ForEach-Object {
    $relative = [System.IO.Path]::GetRelativePath($BundlePath, $_.FullName)
    $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $relative"
} | Set-Content -LiteralPath (Join-Path $EvidencePath "frozen-output-sha256.txt") -Encoding ascii
