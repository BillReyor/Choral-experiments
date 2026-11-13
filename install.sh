#!/bin/sh
# Palare Piano - install it, or bring an installed copy up to date.
#
#     curl -fsSL https://raw.githubusercontent.com/BillReyor/Palare-Piano/main/install.sh | sh
#
# Paste that line into Terminal once.  It needs no password and changes nothing outside three places:
#
#     ~/Library/Application Support/Palare-Piano    the program, its own Python, and (later) the voice model
#     ~/Applications/Palare Piano.app               what you double-click from then on
#     ~/Music/Palare Piano                          your pieces and their tracks (made when you add the first)
#
# What it fetches, and from where: uv (astral.sh), which brings a private Python; this program (github.com);
# the Python packages listed in install/ (pypi.org); the scan reader's models (github.com).  Real voices are
# added later from the page, if you want them.
#
#     ... | sh -s -- --uninstall       removes the first two places (your pieces and tracks are left alone)
#
# For testing: PALARE_HOME, PALARE_LAUNCHER and PALARE_SOURCE (a folder, or the address of a .tar.gz) name
# other places; PALARE_NO_OPEN=1 does not open the app at the end.
set -eu

NAME="Palare Piano"
BASE="${PALARE_HOME:-$HOME/Library/Application Support/Palare-Piano}"
APP="$BASE/app"
LAUNCHER="${PALARE_LAUNCHER:-$HOME/Applications/$NAME.app}"
SOURCE="${PALARE_SOURCE:-https://github.com/BillReyor/Palare-Piano/archive/refs/heads/main.tar.gz}"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
fail() { printf '\n%s\n' "$*" >&2; exit 1; }

if [ "${1:-}" = "--uninstall" ]; then
    rm -rf "$BASE" "$LAUNCHER"
    say "$NAME is removed. Your pieces and tracks are still in ~/Music/$NAME."
    exit 0
fi

# ---- is this a computer it has been tried on?
[ "$(uname -s)" = "Darwin" ] || fail "This installer is for Macs. On another computer, see docs/install-by-hand.md in the project."
[ "$(uname -m)" = "arm64" ] || fail "This installer needs a Mac with an Apple chip (M1 or later). On an Intel Mac, see docs/install-by-hand.md in the project."
major="$(sw_vers -productVersion | cut -d. -f1)"
[ "$major" -ge 14 ] || fail "This needs macOS 14 (Sonoma) or later; this Mac has $(sw_vers -productVersion)."

say "Installing $NAME. This takes a few minutes and about 1.5 GB."

# ---- Apple's developer tools: the compiler one package is built with, and the text reader for scanned music
if ! xcode-select -p >/dev/null 2>&1 || ! /usr/bin/xcrun --find swiftc >/dev/null 2>&1; then
    say "Apple's developer tools are needed first (free, from Apple, about 15 minutes)."
    echo "A window is opening: click Install there. Leave this window open; it goes on by itself afterwards."
    xcode-select --install >/dev/null 2>&1 || true
    until xcode-select -p >/dev/null 2>&1 && /usr/bin/xcrun --find swiftc >/dev/null 2>&1; do sleep 10; done
fi

# ---- uv: fetches a Python of our own, so nothing depends on what this Mac has
mkdir -p "$BASE/bin"
if [ ! -x "$BASE/bin/uv" ]; then
    say "Fetching the tool that installs Python..."
    curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$BASE/bin" UV_NO_MODIFY_PATH=1 INSTALLER_NO_MODIFY_PATH=1 UV_PRINT_QUIET=1 sh >/dev/null 2>&1 \
        || fail "Could not fetch uv from astral.sh. Check the internet connection and run the same line again."
    [ -x "$BASE/bin/uv" ] || { [ -x "$BASE/bin/bin/uv" ] && ln -sf "$BASE/bin/bin/uv" "$BASE/bin/uv"; }
fi
UV="$BASE/bin/uv"
[ -x "$UV" ] || fail "uv did not install where expected ($BASE/bin)."
export UV_PYTHON_INSTALL_DIR="$BASE/python" UV_CACHE_DIR="$BASE/cache" UV_PYTHON_PREFERENCE=only-managed UV_NO_PROGRESS=1

# ---- the program
say "Fetching the program..."
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir "$TMP/src"
if [ -d "$SOURCE" ]; then
    rsync -a --exclude .git --exclude '.venv*' --exclude .svc --exclude out --exclude 'scores/private' --exclude __pycache__ --exclude .DS_Store --exclude '*.preset.json' "$SOURCE/" "$TMP/src/"
else
    curl -fsSL "$SOURCE" -o "$TMP/src.tar.gz" || fail "Could not fetch the program from github.com. Check the internet connection and run the same line again."
    tar -xzf "$TMP/src.tar.gz" -C "$TMP/src" --strip-components 1
fi
[ -f "$TMP/src/choral/app.py" ] || fail "What was fetched is not the program."
mkdir -p "$APP"
rsync -a --delete --exclude .venv --exclude .venv-omr --exclude .svc --exclude __pycache__ "$TMP/src/" "$APP/"

# ---- its Python and packages
say "Installing Python and the program's packages..."
[ -x "$APP/.venv/bin/python" ] || "$UV" venv -q --seed --python 3.12 "$APP/.venv"
"$UV" pip install -q --python "$APP/.venv/bin/python" -r "$APP/install/app.txt"

say "Installing the reader for scanned music..."
[ -x "$APP/.venv-omr/bin/python" ] || "$UV" venv -q --seed --python 3.12 "$APP/.venv-omr"
"$UV" pip install -q --python "$APP/.venv-omr/bin/python" -r "$APP/install/scan-reader.txt"
"$APP/.venv-omr/bin/homr" --init >/dev/null 2>&1 || fail "The scan reader could not fetch its models. Check the internet connection and run the same line again."
"$UV" cache clean -q >/dev/null 2>&1 || true          # what was downloaded is installed now: the copies are not needed

# ---- does it sing?
say "Trying it..."
( cd "$APP" && "$APP/.venv/bin/python" -m choral scores/demo_shenandoah.score --singers 4 --out "$TMP/try" >"$TMP/try.log" 2>&1 ) \
    || { tail -5 "$TMP/try.log" >&2; fail "The program is installed but could not sing its test piece."; }

# ---- what you double-click
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
cat > "$LAUNCHER/Contents/MacOS/launcher" <<EOF
#!/bin/sh
# Starts Palare Piano (or finds it already running) and opens its page.  Written by install.sh.
# The program is left running behind the page and this launcher ends at once, so that opening
# the app again - after the page was closed, say - runs this again and brings the page back.
cd "$APP" || exit 1
nohup "$APP/.venv/bin/python" -m choral.app >> "$BASE/app.log" 2>&1 &
EOF
chmod +x "$LAUNCHER/Contents/MacOS/launcher"
date '+installed %Y-%m-%d %H:%M' > "$BASE/installed.txt"

say "$NAME is installed."
echo "From now on, open \"$NAME\" from the Applications folder in your home folder, or find it with Spotlight."
echo "To bring it up to date later, paste the same line into Terminal again."
if [ -z "${PALARE_NO_OPEN:-}" ]; then
    echo "Opening it now..."
    open "$LAUNCHER"
fi
