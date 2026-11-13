#!/bin/sh
# The whole test of an install, on this computer (a Mac, or Linux).
#
#     sh tools/try_here.sh              the program as it is in this folder
#     sh tools/try_here.sh VERSION      the program as it was at that version (a commit)
#     sh tools/try_here.sh --here       into this user's own home, not an empty one made for the purpose
#
# What it does is what a person would, twice over: runs the installer; opens the installed copy and uses it as a
# singer would (tools/try_install.py: the demo piece read, a note fixed, tracks for every part made and listened
# to, the files to share, the computer check, a report); looks for both readers; runs the installer again over the
# installed copy and uses that; removes it.  Anything that does not go as it should ends it there, saying what.
#
# It is done in an empty home folder made for the purpose and thrown away afterwards, with nothing of this user's
# set-up passed in: a copy of Palare Piano that is installed on this computer, and its pieces, are not touched or
# even seen.  (--here is for a machine that exists only for the test, as GitHub's do.)  It downloads what the
# installer downloads - Python, the packages, the scan reader's models: under a gigabyte - each time.
#
# GitHub runs this on Linux at every change (.github/workflows/install.yml).  For the Mac it is run on a Mac, by
# tools/release.sh, because GitHub's own Macs were too often not to be had.
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HERE=""; VERSION=""
for a in "$@"; do
    case "$a" in
        --here) HERE=1 ;;
        -*) echo "try_here.sh: no such choice: $a" >&2; exit 2 ;;
        *) VERSION="$a" ;;
    esac
done

WORK="$(mktemp -d)"
SRC="$WORK/src"
mkdir "$SRC"
if [ -n "$HERE" ]; then H="$HOME"; else H="$WORK/home"; mkdir "$H"; fi
case "$(uname -s)" in
    Darwin) BASE="$H/Library/Application Support/Palare-Piano" ;;
    *)      BASE="$H/.local/share/Palare-Piano" ;;
esac
PY="$BASE/app/.venv/bin/python"

# every step is run with this home and, unless --here, with nothing else of the user's
in_home() {
    if [ -n "$HERE" ]; then env "$@"; else env -i HOME="$H" PATH="/usr/bin:/bin:/usr/sbin:/sbin" "$@"; fi
}
step() { printf '\n== %s\n' "$*"; }
ended() {
    code=$?
    if [ -f "$BASE/version.json" ]; then                # something was left installed: stop it if it runs, and take it away
        in_home PALARE_NO_OPEN=1 sh "$SRC/install.sh" --uninstall >/dev/null 2>&1 || true
    fi
    rm -rf "$WORK"
    [ "$code" -eq 0 ] || printf '\nNOT RIGHT here: the test stopped at the step above.\n' >&2
    exit "$code"
}
trap ended EXIT

# ---- the program to test: exactly that version, or this folder as it is - without what is private or was made here
if [ -n "$VERSION" ]; then
    VERSION="$(git -C "$ROOT" rev-parse --verify "$VERSION^{commit}")"
    git -C "$ROOT" archive "$VERSION" | tar -xf - -C "$SRC"
    echo "Testing version $(git -C "$ROOT" log -1 --format='%h %s' "$VERSION")"
elif git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
    ( cd "$ROOT" && git ls-files -co --exclude-standard -z | tar --null -T - -cf - ) | tar -xf - -C "$SRC"
    echo "Testing the program as it is in $ROOT"
else
    ( cd "$ROOT" && tar -cf - . ) | tar -xf - -C "$SRC"
    echo "Testing the program as it is in $ROOT"
fi

step "Installing it"
in_home PALARE_SOURCE="$SRC" PALARE_NO_OPEN=1 sh "$SRC/install.sh"

step "Using it as a singer would: every part, the tracks listened to"
in_home "$PY" "$SRC/tools/try_install.py" --part-all --plain

step "The readers are there"
in_home "$PY" -c "import pymupdf, numpy, scipy, PIL; print('PDF reader: pymupdf', pymupdf.__version__)"
in_home "$BASE/app/.venv-omr/bin/python" -c "import homr, onnxruntime; print('scan reader: homr, onnxruntime', onnxruntime.__version__)"

step "Bringing it up to date over itself, and using that"
in_home PALARE_SOURCE="$SRC" PALARE_NO_OPEN=1 sh "$SRC/install.sh"
in_home "$PY" "$SRC/tools/try_install.py"

step "Taking it away"
in_home sh "$SRC/install.sh" --uninstall
if [ -e "$BASE" ]; then echo "It is still there after it was removed: $BASE" >&2; exit 1; fi

printf '\nALL RIGHT here (%s %s).\n' "$(uname -s)" "$(uname -m)"
