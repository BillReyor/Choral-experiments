#!/bin/sh
# The unit tests (tests/), on this computer (a Mac, or Linux).
#
#     sh tools/test.sh                  all of them: under a minute
#     sh tools/test.sh -k upbeat        whatever pytest takes: here, only the tests with "upbeat" in their names
#     sh tools/test.sh --at VERSION     the tests of that version (a commit), on that version - not this folder as it is
#
# The first time, it makes a Python for the purpose in .venv-test/ (which git ignores): the program's packages at
# the versions the installer installs, pytest, and - where it can be built - pyworld, without which the tests of a
# real voice's rebuilt tone are skipped.  About 200 MB, downloaded once, and again only when the installer's lists
# of packages change.  It is made with uv: the one on the path, or the one a copy of Palare Piano installed on this
# computer brought with it.  With neither, the python3 on the path is used, if it is new enough for the packages.
#
# Nothing here touches an installed copy, its pieces, or the internet (beyond that first download): the tests make
# their own music, and a page server that answers only them.  GitHub runs the same tests on Linux and Windows
# (.github/workflows/tests.yml); tools/release.sh runs them here before a version is given out.
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT"; WORK=""
if [ "${1:-}" = "--at" ]; then
    [ -n "${2:-}" ] || { echo "test.sh: --at needs a version" >&2; exit 2; }
    VERSION="$(git -C "$ROOT" rev-parse --verify "$2^{commit}")"
    shift 2
    WORK="$(mktemp -d)"
    trap 'rm -rf "$WORK"' EXIT
    git -C "$ROOT" archive "$VERSION" | tar -xf - -C "$WORK"
    SRC="$WORK"
    echo "Testing version $(git -C "$ROOT" log -1 --format='%h %s' "$VERSION")"
fi

ENV="$ROOT/.venv-test"
PY="$ENV/bin/python"
WANT="$(cat "$SRC/install/app.txt" "$SRC/install/tracks.txt" | cksum)"
if [ ! -x "$PY" ] || [ "$(cat "$ENV/made-for" 2>/dev/null || true)" != "$WANT" ]; then
    echo "Making a Python for the tests in .venv-test/ (once: a few minutes)..."
    UV=""
    for u in "$(command -v uv 2>/dev/null || true)" "$HOME/Library/Application Support/Palare-Piano/bin/uv" "$HOME/.local/share/Palare-Piano/bin/uv"; do
        if [ -n "$u" ] && [ -x "$u" ]; then UV="$u"; break; fi
    done
    rm -rf "$ENV"
    if [ -n "$UV" ]; then
        "$UV" venv -q --seed --python 3.12 "$ENV"
        "$UV" pip install -q --python "$PY" -r "$SRC/install/app.txt" -r "$SRC/install/tracks.txt" pytest
        "$UV" pip install -q --python "$PY" pyworld==0.3.5 "setuptools<81" >/dev/null 2>&1 \
            || echo "  (pyworld could not be built here: the tests that need it will be skipped)"
    else
        python3 -m venv "$ENV" && "$PY" -m pip install -q --disable-pip-version-check -r "$SRC/install/app.txt" -r "$SRC/install/tracks.txt" pytest || {
            rm -rf "$ENV"
            echo "Could not make it with the python3 on this computer. Install uv (https://docs.astral.sh/uv/) or Palare Piano itself, and run this again." >&2
            exit 1
        }
        "$PY" -m pip install -q --disable-pip-version-check pyworld==0.3.5 "setuptools<81" >/dev/null 2>&1 \
            || echo "  (pyworld could not be built here: the tests that need it will be skipped)"
    fi
    echo "$WANT" > "$ENV/made-for"
fi

cd "$SRC"
"$PY" -m pytest -q -p no:cacheprovider "$@"
