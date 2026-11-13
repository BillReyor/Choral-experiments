#!/bin/sh
# The reader, tried on real sheet music - your own - before and after a change to it.
#
#     sh tools/reread.sh                 read every PDF under scores/private/ with the reader as it is in this folder,
#                                        and say which readings differ from the ones accepted last time
#     sh tools/reread.sh --accept        ... and accept these readings: they are what the next run is compared with
#     sh tools/reread.sh FOLDER          the PDFs under another folder
#
# The unit tests (tools/test.sh) draw their own music, because no sheet music may be in this repository.  They
# cannot say what a change to the reader does to the pieces people actually sing from - a scan with a coffee ring,
# an engraver's habit nobody thought of.  This can: every measure that reads differently after a change is either
# what the change was for, or a mistake, and each is looked at against the page before the change is given out.
#
# The readings are kept in out/readings/ (accepted/, now/ and, between runs, the page images and the scan reader's
# work, which are most of the time a reading takes): git ignores out/, as it ignores scores/private/.  Nothing is
# sent anywhere.  The first run reads every page with the scan reader and takes a few minutes a piece.
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="$ROOT/scores/private"; ACCEPT=""
for a in "$@"; do
    case "$a" in
        --accept) ACCEPT=1 ;;
        -*) echo "reread.sh: no such choice: $a" >&2; exit 2 ;;
        *) DIR="$(cd "$a" && pwd)" ;;
    esac
done
OUT="$ROOT/out/readings"
PY="$ROOT/.venv-test/bin/python"
[ -x "$PY" ] || sh "$ROOT/tools/test.sh" --collect-only >/dev/null        # (makes that Python, and runs nothing)
[ -x "$ROOT/.venv-omr/bin/homr" ] && export HOMR="$ROOT/.venv-omr/bin/homr"

rm -rf "$OUT/now"
mkdir -p "$OUT/now" "$OUT/work" "$OUT/accepted"

one() {
    pdf="$1"
    name="$(printf '%s' "${pdf#"$DIR"/}" | sed -e 's/\.pdf$//' -e 's#/#__#g')"
    work="$OUT/work/$name.scan"
    if [ ! -d "$work" ]; then                           # (a piece the program has read before has its pages beside it)
        if [ -d "${pdf%.pdf}.scan" ]; then cp -R "${pdf%.pdf}.scan" "$work"; else mkdir -p "$work"; fi
    fi
    ( cd "$ROOT" && "$PY" tools/scan2score.py "$pdf" "$OUT/now/$name.score" --work "$work" ) >"$OUT/now/$name.log" 2>&1 \
        || echo "could not be read: see the .log beside it" >"$OUT/now/$name.failed"
}

find "$DIR" -name '*.pdf' -not -path '*.scan/*' | sort | {
    while IFS= read -r pdf; do one "$pdf" & done
    wait
}

changed=0; n=0
for f in "$OUT/now"/*.log; do
    [ -e "$f" ] || { echo "No PDF under $DIR."; exit 0; }
    name="$(basename "$f" .log)"; n=$((n + 1))
    if [ -e "$OUT/now/$name.failed" ]; then
        echo "  NOT READ   $name"; changed=$((changed + 1))
    elif [ ! -e "$OUT/accepted/$name.score" ]; then
        echo "  new        $name"
    elif cmp -s "$OUT/accepted/$name.score" "$OUT/now/$name.score"; then
        echo "  the same   $name"
    else
        diff "$OUT/accepted/$name.score" "$OUT/now/$name.score" >"$OUT/now/$name.diff" || true
        echo "  CHANGED    $name   ($(grep -c '^[<>]' "$OUT/now/$name.diff") lines: out/readings/now/$name.diff)"
        changed=$((changed + 1))
    fi
done

if [ -n "$ACCEPT" ]; then
    rm -rf "$OUT/accepted"; cp -R "$OUT/now" "$OUT/accepted"
    echo "$n pieces read; these readings are now the accepted ones."
elif [ "$changed" -gt 0 ]; then
    echo "$n pieces read; $changed differ from the accepted readings. Look at each against its page; then  sh tools/reread.sh --accept"
    exit 1
else
    echo "$n pieces read; none differs from the accepted readings."
fi
