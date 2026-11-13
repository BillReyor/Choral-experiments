# Palare Piano for Windows - install it, or bring an installed copy up to date.
# (Macs and Linux have install.sh, which does the same there.)
#
#     irm https://raw.githubusercontent.com/BillReyor/Palare-Piano/main/install.ps1 | iex
#
# Paste that line into PowerShell once.  It needs no administrator, and what it installs is in three places:
#
#     %LOCALAPPDATA%\Palare-Piano          the program and its own Python
#     "Palare Piano" in the Start menu     what you open from then on (and the same on the Desktop)
#     Music\Palare Piano                   your pieces and their tracks (made when you add the first)
#
# What it fetches, and from where: uv (github.com), which brings a private Python; this program (github.com);
# the Python packages listed in install\ (pypi.org); the scan reader's models (github.com).  The parts that
# would report their use to their makers (onnxruntime, the Hugging Face downloader) are told not to.
#
#     $env:PALARE_UNINSTALL = 1; irm https://raw.githubusercontent.com/BillReyor/Palare-Piano/main/install.ps1 | iex
#
# removes the first two places (your pieces and tracks are left alone).
#
# For testing: PALARE_HOME, PALARE_LAUNCHER, PALARE_LIBRARY and PALARE_SOURCE (a folder, or the address of
# a .zip) name other places; PALARE_NO_OPEN=1 does not open the app at the end.
#
# This file is plain ASCII on purpose: Windows PowerShell 5.1 reads anything else wrongly when it is piped in.

function Install-PalarePiano {
    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue'           # its progress bar makes downloads many times slower
    try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch {}

    $Name = 'Palare Piano'
    $Repo = 'BillReyor/Palare-Piano'
    $Base = if ($env:PALARE_HOME) { $env:PALARE_HOME } else { Join-Path $env:LOCALAPPDATA 'Palare-Piano' }
    $App = Join-Path $Base 'app'
    $Lib = if ($env:PALARE_LIBRARY) { $env:PALARE_LIBRARY } else { Join-Path $env:USERPROFILE "Music\$Name" }
    $Menu = Join-Path ([Environment]::GetFolderPath('Programs')) "$Name.lnk"
    $Desk = Join-Path ([Environment]::GetFolderPath('Desktop')) "$Name.lnk"
    $Links = if ($env:PALARE_LAUNCHER) { @($env:PALARE_LAUNCHER) } else { @($Menu, $Desk) }
    $Py = Join-Path $App '.venv\Scripts\python.exe'
    $Source = $env:PALARE_SOURCE

    function Say($text) { Write-Host ''; Write-Host $text -ForegroundColor Cyan }
    function Run($what, $exe, $rest) {
        # a program's own messages go to a file; only if it fails are its last lines shown
        $log = Join-Path $Base 'install.log'
        $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        & $exe @rest > $log 2>&1
        $code = $LASTEXITCODE
        $ErrorActionPreference = $old
        if ($code -ne 0) {
            Get-Content $log -Tail 12 | ForEach-Object { Write-Host "    $_" }
            throw $what
        }
    }

    # ---- a copy that is running: closed first, so that what opens afterwards is the new one - unless it is busy
    function Close-Running($evenIfBusy) {
        $note = Join-Path $Lib '.server.json'
        if (-not (Test-Path $note)) { return }
        try { $n = Get-Content $note -Raw | ConvertFrom-Json } catch { return }
        $p = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$n.pid)" -ErrorAction SilentlyContinue
        if (-not $p -or "$($p.CommandLine)" -notmatch 'choral\.app') { return }
        if (-not $evenIfBusy) {
            $busy = $false
            try { $busy = $null -ne (Invoke-RestMethod "http://127.0.0.1:$($n.port)/api/state" -TimeoutSec 3).job } catch {}
            if ($busy) { throw "$Name is in the middle of making something. Let it finish, or stop it on its page, and then paste the same line again." }
        }
        Say "Closing the copy of $Name that is open..."
        Stop-Process -Id $n.pid -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }

    try {
        if ($env:PALARE_UNINSTALL) {
            $env:PALARE_UNINSTALL = $null
            Close-Running $true
            foreach ($l in $Links) { if (Test-Path $l) { Remove-Item $l -Force } }
            if (Test-Path $Base) { Remove-Item $Base -Recurse -Force }
            Say "$Name is removed. Your pieces and tracks are still in $Lib."
            return
        }

        # ---- is this a computer it has been tried on?
        if (-not [Environment]::Is64BitOperatingSystem) { throw 'This needs 64-bit Windows.' }
        if ([Environment]::OSVersion.Version.Major -lt 10) { throw 'This needs Windows 10 or later.' }
        $arm = $env:PROCESSOR_ARCHITECTURE -eq 'ARM64'

        Say "Installing $Name. This takes a few minutes and about 1.5 GB."
        New-Item -ItemType Directory -Force -Path (Join-Path $Base 'bin') | Out-Null
        $Tmp = Join-Path ([IO.Path]::GetTempPath()) ("palare-" + [Guid]::NewGuid().ToString('N').Substring(0, 8))
        New-Item -ItemType Directory -Force -Path $Tmp | Out-Null

        # ---- uv: fetches a Python of our own, so nothing depends on what this computer has
        $Uv = Join-Path $Base 'bin\uv.exe'
        if (-not (Test-Path $Uv)) {
            Say 'Fetching the tool that installs Python...'
            $kind = if ($arm) { 'aarch64' } else { 'x86_64' }
            try {
                Invoke-WebRequest "https://github.com/astral-sh/uv/releases/latest/download/uv-$kind-pc-windows-msvc.zip" -OutFile (Join-Path $Tmp 'uv.zip') -UseBasicParsing
            } catch { throw 'Could not fetch uv from github.com. Check the internet connection and paste the same line again.' }
            Expand-Archive (Join-Path $Tmp 'uv.zip') -DestinationPath (Join-Path $Tmp 'uv') -Force
            Get-ChildItem (Join-Path $Tmp 'uv') -Recurse -Filter '*.exe' | Copy-Item -Destination (Join-Path $Base 'bin') -Force
        }
        if (-not (Test-Path $Uv)) { throw "uv did not install where expected ($Base\bin)." }
        $env:UV_PYTHON_INSTALL_DIR = Join-Path $Base 'python'
        $env:UV_CACHE_DIR = Join-Path $Base 'cache'
        $env:UV_PYTHON_PREFERENCE = 'only-managed'
        $env:UV_PYTHON_INSTALL_REGISTRY = '0'          # this Python is the program's own: Windows is not told about it
        $env:UV_PYTHON_INSTALL_BIN = '0'
        $env:UV_NO_PROGRESS = '1'
        $env:ORT_DISABLE_TELEMETRY = '1'
        $env:HF_HUB_DISABLE_TELEMETRY = '1'
        # on a Windows computer with an ARM chip the parts are not all made for it: use the ordinary ones, which it can run
        $Python = if ($arm) { 'cpython-3.12-windows-x86_64-none' } else { '3.12' }

        Close-Running $false

        # ---- the program: which version is the newest, then exactly that one (the page later asks whether there is a newer)
        Say 'Fetching the program...'
        $Src = Join-Path $Tmp 'src'
        New-Item -ItemType Directory -Force -Path $Src | Out-Null
        $Version = 'local'
        if (-not $Source) {
            $Version = 'unknown'
            try { $Version = (Invoke-RestMethod "https://api.github.com/repos/$Repo/commits/main" -TimeoutSec 20 -Headers @{ 'User-Agent' = 'palare-piano-installer' }).sha } catch {}
            $Source = if ($Version -match '^[0-9a-f]{40}$') { "https://github.com/$Repo/archive/$Version.zip" } else { $Version = 'unknown'; "https://github.com/$Repo/archive/refs/heads/main.zip" }
        }
        if (Test-Path $Source -PathType Container) {
            # a folder: everything in it that is the program - not its history, its environments, its voices,
            # what it has rendered, or anything private
            & robocopy $Source $Src /E /XD .git .github .venv .venv-omr .svc out __pycache__ private /XF *.preset.json .DS_Store /NFL /NDL /NJH /NJS /NP | Out-Null
            if ($LASTEXITCODE -ge 8) { throw 'Could not copy the program from the folder given.' }
        } else {
            try {
                Invoke-WebRequest $Source -OutFile (Join-Path $Tmp 'src.zip') -UseBasicParsing
            } catch { throw 'Could not fetch the program from github.com. Check the internet connection and paste the same line again.' }
            Expand-Archive (Join-Path $Tmp 'src.zip') -DestinationPath (Join-Path $Tmp 'unzipped') -Force
            $top = Get-ChildItem (Join-Path $Tmp 'unzipped') -Directory | Select-Object -First 1
            Get-ChildItem $top.FullName -Force | Move-Item -Destination $Src
        }
        if (-not (Test-Path (Join-Path $Src 'choral\app.py'))) { throw 'What was fetched is not the program.' }
        New-Item -ItemType Directory -Force -Path $App | Out-Null
        # out with the old program's files - not its Python, its scan reader or its voices, which stay where they are - and in with the new
        Get-ChildItem $App -Force | Where-Object { $_.Name -notin '.venv', '.venv-omr', '.svc' } | Remove-Item -Recurse -Force
        Get-ChildItem $Src -Force | Copy-Item -Destination $App -Recurse -Force

        # ---- its Python and packages
        Say "Installing Python and the program's packages..."
        if (-not (Test-Path $Py)) { Run 'Python could not be installed.' $Uv @('venv', '-q', '--seed', '--python', $Python, (Join-Path $App '.venv')) }
        Run "The program's packages could not be installed." $Uv @('pip', 'install', '-q', '--python', $Py, '-r', (Join-Path $App 'install\app.txt'))

        Say 'Installing the reader for scanned music...'
        $OmrPy = Join-Path $App '.venv-omr\Scripts\python.exe'
        if (-not (Test-Path $OmrPy)) { Run 'Python could not be installed for the scan reader.' $Uv @('venv', '-q', '--seed', '--python', $Python, (Join-Path $App '.venv-omr')) }
        Run 'The scan reader could not be installed.' $Uv @('pip', 'install', '-q', '--python', $OmrPy, '-r', (Join-Path $App 'install\scan-reader.txt'))
        Run 'The scan reader could not fetch its models. Check the internet connection and paste the same line again.' (Join-Path $App '.venv-omr\Scripts\homr.exe') @('--init')
        try { & $Uv cache clean -q 2>&1 | Out-Null } catch {}       # what was downloaded is installed now: the copies are not needed

        # ---- does it sing?
        Say 'Trying it...'
        $env:PYTHONUTF8 = '1'
        Push-Location $App
        try {
            Run 'The program is installed but could not sing its test piece.' $Py @('-m', 'choral', 'scores\demo_shenandoah.score', '--singers', '4', '--out', (Join-Path $Tmp 'try'))
        } finally { Pop-Location }

        # ---- what you open from now on: the program without a black window behind it.  Opening it again -
        # after the page was closed, say - finds it running and brings the page back.
        $shell = New-Object -ComObject WScript.Shell
        foreach ($l in $Links) {
            New-Item -ItemType Directory -Force -Path (Split-Path $l) | Out-Null
            $s = $shell.CreateShortcut($l)
            $s.TargetPath = Join-Path $App '.venv\Scripts\pythonw.exe'
            $s.Arguments = '-X utf8 -m choral.app'
            $s.WorkingDirectory = $App
            $s.Description = 'Sheet music in, rehearsal tracks out'
            $s.Save()
        }
        $when = Get-Date -Format 'yyyy-MM-dd HH:mm'
        $json = @{ version = $Version; installed = $when; launcher = $Links[0]; start = $Links[0] } | ConvertTo-Json -Compress
        [IO.File]::WriteAllText((Join-Path $Base 'version.json'), $json)       # (written this way, it has no mark at its start that Python would trip on)
        Remove-Item $Tmp -Recurse -Force -ErrorAction SilentlyContinue

        Say "$Name is installed."
        Write-Host "From now on, open `"$Name`" from the Start menu, or from its icon on the Desktop."
        $tess = (Get-Command tesseract -ErrorAction SilentlyContinue) -or (Test-Path (Join-Path $env:ProgramFiles 'Tesseract-OCR\tesseract.exe'))
        if (-not $tess) { Write-Host 'One more thing, for scanned music only: its words are read by a free program called Tesseract, which is not on this computer. The README says how to add it. Music saved as a PDF by notation software does not need it.' }
        if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { Write-Host 'Tracks will be saved as .wav files, which are large. With ffmpeg installed they are saved small, as .m4a (the README says how).' }
        Write-Host 'To bring it up to date later, use the button on its page, or paste the same line again.'
        if (-not $env:PALARE_NO_OPEN) {
            Write-Host 'Opening it now...'
            Start-Process -FilePath $Links[0]
        }
    } catch {
        Write-Host ''
        Write-Host "$($_.Exception.Message)" -ForegroundColor Red
        Write-Host "$Name was not installed. Nothing else on this computer was changed." -ForegroundColor Red
        $global:PalareFailed = $true
    }
}

$global:PalareFailed = $false
Install-PalarePiano
if ($global:PalareFailed -and $env:PALARE_STRICT) { exit 1 }       # (for automatic tests; a person's window is never closed)
