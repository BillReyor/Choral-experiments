#!/bin/sh
# Palare Piano - install it, or bring an installed copy up to date.  For Macs and for Linux
# (Windows has install.ps1, which does the same there).
#
#     curl -fsSL https://raw.githubusercontent.com/BillReyor/Palare-Piano/main/install.sh | sh
#     wget -qO- https://raw.githubusercontent.com/BillReyor/Palare-Piano/main/install.sh | sh      (where there is no curl)
#
# Paste one of those lines into a terminal once.  It needs no password, and what it installs is in three places:
#
#     the program, its own Python, and (on a Mac, later) the voice model
#         on a Mac    ~/Library/Application Support/Palare-Piano
#         on Linux    ~/.local/share/Palare-Piano
#     what you open from then on
#         on a Mac    ~/Applications/Palare Piano.app
#         on Linux    "Palare Piano" among your applications (~/.local/share/applications/palare-piano.desktop)
#     your pieces and their tracks (made when you add the first)
#         ~/Music/Palare Piano
#
# What it fetches, and from where: uv (astral.sh), which brings a private Python; this program (github.com);
# the Python packages listed in install/ (pypi.org); the scan reader's models (github.com).  Real voices are
# added later from the page, if you want them and the computer can run them.  The parts that would report their
# use to their makers (onnxruntime, the Hugging Face downloader) are told not to.  If Apple's developer tools
# are missing on a Mac, Apple installs them where it keeps them.
#
#     ... | sh -s -- --uninstall       removes the first two places (your pieces and tracks are left alone)
#
# For testing: PALARE_HOME, PALARE_LAUNCHER and PALARE_SOURCE (a folder, or the address of a .tar.gz) name
# other places; PALARE_NO_OPEN=1 does not open the app at the end.
set -eu

NAME="Palare Piano"
REPO="BillReyor/Palare-Piano"
SOURCE="${PALARE_SOURCE:-}"
OS="$(uname -s)"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
fail() { printf '\n%s\n' "$*" >&2; exit 1; }
# get ADDRESS [SECONDS]: what is at that address, by whichever of the two fetching programs this computer has
if command -v curl >/dev/null 2>&1; then
    get() { curl -fsSL -m "${2:-900}" "$1"; }
elif command -v wget >/dev/null 2>&1; then
    get() { wget -q -T "${2:-900}" -t 1 -O - "$1"; }
else
    fail "This needs the 'curl' program (or 'wget'), and this computer has neither. Install one (on Ubuntu: sudo apt install curl) and run the same line again."
fi

case "$OS" in
    Darwin)
        BASE="${PALARE_HOME:-$HOME/Library/Application Support/Palare-Piano}"
        LAUNCHER="${PALARE_LAUNCHER:-$HOME/Applications/$NAME.app}"
        START="$LAUNCHER/Contents/MacOS/launcher" ;;
    Linux)
        BASE="${PALARE_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/Palare-Piano}"
        LAUNCHER="${PALARE_LAUNCHER:-${XDG_DATA_HOME:-$HOME/.local/share}/applications/palare-piano.desktop}"
        START="$BASE/palare-piano" ;;
    *)
        fail "This installer is for Macs and Linux. On Windows, use the PowerShell line in the README." ;;
esac
APP="$BASE/app"

if [ "${1:-}" = "--uninstall" ]; then
    rm -rf "$BASE" "$LAUNCHER"
    say "$NAME is removed. Your pieces and tracks are still in ~/Music/$NAME."
    exit 0
fi

# ---- is this a computer it has been tried on?
if [ "$OS" = "Darwin" ]; then
    [ "$(uname -m)" = "arm64" ] || fail "This installer needs a Mac with an Apple chip (M1 or later). On an Intel Mac, see docs/install-by-hand.md in the project."
    major="$(sw_vers -productVersion | cut -d. -f1)"
    [ "$major" -ge 14 ] || fail "This needs macOS 14 (Sonoma) or later; this Mac has $(sw_vers -productVersion)."
else
    case "$(uname -m)" in
        x86_64|aarch64|arm64) ;;
        *) fail "This computer's processor ($(uname -m)) is not one the program's parts are made for." ;;
    esac
    command -v tar >/dev/null 2>&1 || fail "This needs the 'tar' program, which is missing here. Install it (on Ubuntu: sudo apt install tar) and run the same line again."
fi

say "Installing $NAME. This takes a few minutes and about 1.5 GB."

# ---- Apple's developer tools: the compiler one package is built with, and the text reader for scanned music
if [ "$OS" = "Darwin" ]; then
    if ! xcode-select -p >/dev/null 2>&1 || ! /usr/bin/xcrun --find swiftc >/dev/null 2>&1; then
        say "Apple's developer tools are needed first (free, from Apple, about 15 minutes)."
        echo "A window is opening: click Install there. Leave this window open; it goes on by itself afterwards."
        xcode-select --install >/dev/null 2>&1 || true
        until xcode-select -p >/dev/null 2>&1 && /usr/bin/xcrun --find swiftc >/dev/null 2>&1; do sleep 10; done
    fi
fi

# ---- uv: fetches a Python of our own, so nothing depends on what this computer has
mkdir -p "$BASE/bin"
if [ ! -x "$BASE/bin/uv" ]; then
    say "Fetching the tool that installs Python..."
    get https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL="$BASE/bin" sh >/dev/null 2>&1 \
        || fail "Could not fetch uv from astral.sh. Check the internet connection and run the same line again."
    [ -x "$BASE/bin/uv" ] || { [ -x "$BASE/bin/bin/uv" ] && ln -sf "$BASE/bin/bin/uv" "$BASE/bin/uv"; }
fi
UV="$BASE/bin/uv"
[ -x "$UV" ] || fail "uv did not install where expected ($BASE/bin)."
export UV_PYTHON_INSTALL_DIR="$BASE/python" UV_CACHE_DIR="$BASE/cache" UV_PYTHON_PREFERENCE=only-managed UV_NO_PROGRESS=1

# ---- a copy that is running is closed first, so that what opens afterwards is the new one - unless it is busy
NOTE="${PALARE_LIBRARY:-$HOME/Music/$NAME}/.server.json"
if [ -f "$NOTE" ]; then
    pid="$(sed -n 's/.*"pid": *\([0-9][0-9]*\).*/\1/p' "$NOTE")"
    port="$(sed -n 's/.*"port": *\([0-9][0-9]*\).*/\1/p' "$NOTE")"
    if [ -n "$pid" ] && ps -p "$pid" -o args= 2>/dev/null | grep -q "choral.app"; then
        if get "http://127.0.0.1:$port/api/state" 3 2>/dev/null | grep -q '"job": {'; then
            fail "$NAME is in the middle of making something. Let it finish, or stop it on its page, and then run the same line again."
        fi
        say "Closing the copy of $NAME that is open, to bring it up to date..."
        kill "$pid" 2>/dev/null || true
        sleep 1
    fi
fi

# ---- the program: which version is the newest, then exactly that one (the page later asks whether there is a newer)
say "Fetching the program..."
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir "$TMP/src"
VERSION="local"
if [ -z "$SOURCE" ]; then
    VERSION="$(get "https://api.github.com/repos/$REPO/commits/main" 20 2>/dev/null | sed -n 's/^  "sha": "\([0-9a-f]\{40\}\)".*/\1/p' | head -1)"
    if [ -n "$VERSION" ]; then
        SOURCE="https://github.com/$REPO/archive/$VERSION.tar.gz"
    else
        VERSION="unknown"; SOURCE="https://github.com/$REPO/archive/refs/heads/main.tar.gz"
    fi
fi
if [ -d "$SOURCE" ]; then
    # a folder: everything in it that is the program - not its history, its environments, its voices,
    # what it has rendered, or anything private
    ( cd "$SOURCE" && for f in * .gitignore; do
        case "$f" in out|__pycache__) continue ;; esac
        [ -e "$f" ] && echo "$f"
      done | tar -cf - --exclude 'scores/private' --exclude __pycache__ --exclude .DS_Store --exclude '*.preset.json' -T - ) | tar -xf - -C "$TMP/src"
else
    get "$SOURCE" > "$TMP/src.tar.gz" || fail "Could not fetch the program from github.com. Check the internet connection and run the same line again."
    tar -xzf "$TMP/src.tar.gz" -C "$TMP/src" --strip-components 1
fi
[ -f "$TMP/src/choral/app.py" ] || fail "What was fetched is not the program."
mkdir -p "$APP"
# out with the old program's files - not its Python, its scan reader or its voices, which stay where they are - and in with the new
find "$APP" -mindepth 1 -maxdepth 1 ! -name .venv ! -name .venv-omr ! -name .svc -exec rm -rf {} +
( cd "$TMP/src" && tar -cf - . ) | tar -xf - -C "$APP"

# ---- its Python and packages
say "Installing Python and the program's packages..."
[ -x "$APP/.venv/bin/python" ] || "$UV" venv -q --seed --python 3.12 "$APP/.venv"
"$UV" pip install -q --python "$APP/.venv/bin/python" -r "$APP/install/app.txt"
if [ "$OS" != "Darwin" ]; then                         # what saves the tracks small (a Mac has a converter of its own)
    "$UV" pip install -q --python "$APP/.venv/bin/python" -r "$APP/install/tracks.txt" >/dev/null 2>&1 || true
fi

say "Installing the reader for scanned music..."
[ -x "$APP/.venv-omr/bin/python" ] || "$UV" venv -q --seed --python 3.12 "$APP/.venv-omr"
"$UV" pip install -q --python "$APP/.venv-omr/bin/python" -r "$APP/install/scan-reader.txt"
ORT_DISABLE_TELEMETRY=1 "$APP/.venv-omr/bin/homr" --init >"$TMP/homr.log" 2>&1 \
    || { tail -5 "$TMP/homr.log" >&2; fail "The scan reader could not fetch its models. Check the internet connection and run the same line again."; }
"$UV" cache clean -q >/dev/null 2>&1 || true          # what was downloaded is installed now: the copies are not needed

# ---- does it sing?
say "Trying it..."
( cd "$APP" && "$APP/.venv/bin/python" -m choral scores/demo_shenandoah.score --singers 4 --out "$TMP/try" >"$TMP/try.log" 2>&1 ) \
    || { tail -5 "$TMP/try.log" >&2; fail "The program is installed but could not sing its test piece."; }

# ---- what you open from now on.  It leaves the program running behind its page and ends at once, so that
# opening it again - after the page was closed, say - starts it again and brings the page back.
if [ "$OS" = "Darwin" ]; then
    mkdir -p "$LAUNCHER/Contents/MacOS"
    cat > "$LAUNCHER/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>$NAME</string>
  <key>CFBundleDisplayName</key><string>$NAME</string>
  <key>CFBundleIdentifier</key><string>org.palare-piano.app</string>
  <key>CFBundleExecutable</key><string>launcher</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSUIElement</key><true/>
</dict></plist>
EOF
else
    mkdir -p "$(dirname "$LAUNCHER")"
    cat > "$LAUNCHER" <<EOF
[Desktop Entry]
Type=Application
Name=$NAME
Comment=Sheet music in, rehearsal tracks out
Exec="$START"
Terminal=false
Categories=AudioVideo;Audio;Music;
EOF
fi
cat > "$START" <<EOF
#!/bin/sh
# Starts Palare Piano (or finds it already running) and opens its page.  Written by install.sh.
cd "$APP" || exit 1
nohup "$APP/.venv/bin/python" -m choral.app >> "$BASE/app.log" 2>&1 &
EOF
chmod +x "$START"
date '+installed %Y-%m-%d %H:%M' > "$BASE/installed.txt"
cat > "$BASE/version.json" <<EOF
{"version": "$VERSION", "installed": "$(date '+%Y-%m-%d %H:%M')", "launcher": "$LAUNCHER", "start": "$START"}
EOF

say "$NAME is installed."
if [ "$OS" = "Darwin" ]; then
    echo "From now on, open \"$NAME\" from the Applications folder in your home folder, or find it with Spotlight."
else
    echo "From now on, open \"$NAME\" from your applications menu."
    command -v tesseract >/dev/null 2>&1 || echo "One more thing, for scanned music only: its words are read by a program called Tesseract, which is not on this computer. Install it (on Ubuntu: sudo apt install tesseract-ocr) and scans will have their words. Music saved as a PDF by notation software does not need it."
    command -v ffmpeg >/dev/null 2>&1 || "$APP/.venv/bin/python" -c "import lameenc" 2>/dev/null \
        || echo "Tracks will be saved as .wav files, which are large. With ffmpeg installed (on Ubuntu: sudo apt install ffmpeg) they are saved small."
fi
echo "To bring it up to date later, use the button on its page, or paste the same line again."
if [ -z "${PALARE_NO_OPEN:-}" ]; then
    echo "Opening it now..."
    if [ "$OS" = "Darwin" ]; then open "$LAUNCHER"; else sh "$START"; fi
fi
