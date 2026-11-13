#!/bin/sh
# Give people the newest version: move the branch "stable" on to where "main" is.
#
#     sh tools/release.sh            look, test if need be, and move it
#     sh tools/release.sh --look     only say what would be given out
#
# Everyone's install line, and the "Update now" button on the page, take the newest version on "stable".  Work is
# pushed to "main" as it goes, so "stable" is what stands between a half-finished change and a singer's computer.
# This moves it only to a version that has passed two tests on all three kinds of computer, at exactly that
# version: the unit tests (tests/: each part's rules, one at a time) and the test of an install (the real
# installer, then tools/try_install.py doing what a singer does).
#
#     Linux and Windows   on GitHub's machines ("installs and sings", which runs both).  If it has not been run at
#                         this version - a change to the documents alone does not start it - it is started here
#                         and waited for.
#     the Mac             on this Mac: tools/test.sh, then tools/try_here.sh in an empty home made for the purpose
#                         (two minutes together; a copy of Palare Piano installed here is not touched).  GitHub's
#                         own Macs were too often not to be had.  When both have passed, that is written beside
#                         the version on GitHub, as "Mac".
#
# GitHub holds to the same rule by itself: "stable" is a protected branch that requires the three checks (Linux,
# Windows, Mac), for the owner too.  A push to it by hand of a version that has not passed them is refused.
#
# It needs git, gh signed in to an account that may push to the repository, and - for the Mac's part - to be run
# on a Mac with an Apple chip.
set -eu

REPO="BillReyor/Palare-Piano"
TEST="install.yml"
cd "$(dirname "$0")/.."

git fetch -q origin main
git fetch -q origin stable 2>/dev/null || true
NEW="$(git rev-parse origin/main)"
OLD="$(git rev-parse -q --verify origin/stable 2>/dev/null || true)"

if [ "$NEW" = "$OLD" ]; then
    echo "Nothing to give out: stable is already at the newest version ($(git log -1 --format='%h %s' "$NEW"))."
    exit 0
fi
if [ -n "$OLD" ] && ! git merge-base --is-ancestor "$OLD" "$NEW"; then
    echo "stable ($OLD) is not an earlier point of main: someone has moved it by hand. Not touching it." >&2
    exit 1
fi

echo "What people would get (newest first):"
if [ -n "$OLD" ]; then git log --format='  %h %s' "$OLD..$NEW"; else git log -8 --format='  %h %s' "$NEW"; fi
[ "${1:-}" = "--look" ] && exit 0

# ---- Linux and Windows, on GitHub
# the newest run of the test at exactly this version -> ID, STATUS and END (how it ended); ID is empty if there is none
look() {
    set -- $(gh run list --repo "$REPO" --workflow "$TEST" --commit "$NEW" --limit 1 --json databaseId,status,conclusion \
                 -q '.[0] // empty | "\(.databaseId) \(.status) \(.conclusion // "-")"' 2>/dev/null || true)
    ID="${1:-}"; STATUS="${2:-}"; END="${3:-}"
}

look
tries=0                                    # (after a push made a moment ago, its test may not be listed yet)
while [ -z "$ID" ] && [ "$tries" -lt 4 ]; do sleep 5; tries=$((tries + 1)); look; done
if [ "$END" != "success" ]; then
    if [ -z "$ID" ]; then                                           # never run at this version: run it
        echo "Starting the test on Linux and Windows at $(git rev-parse --short "$NEW")..."
        gh workflow run "$TEST" --repo "$REPO" --ref main >/dev/null
    elif [ "$STATUS" = "completed" ]; then                          # run, and not passed: run again what did not pass
        echo "Last time the test on GitHub ended: $END. Running again the part that did not pass..."
        gh run rerun "$ID" --repo "$REPO" --failed >/dev/null
        STATUS=""
    fi
    tries=0
    until [ -n "$ID" ] && [ -n "$STATUS" ] && [ "$STATUS" != "completed" ]; do
        sleep 5; look
        tries=$((tries + 1)); [ "$tries" -lt 24 ] || { echo "The test did not start. Look at the Actions page of the repository." >&2; exit 1; }
    done
fi

# ---- the Mac, here (while GitHub gets on with the other two)
mac_passed() {
    [ "$(gh api "repos/$REPO/commits/$NEW/statuses" -q '[.[] | select(.context == "Mac")][0].state // empty' 2>/dev/null || true)" = "success" ]
}
note_mac() { gh api -X POST "repos/$REPO/statuses/$NEW" -f state="$1" -f context=Mac -f description="$2" >/dev/null; }

if mac_passed; then
    echo "The Mac: passed at this version already."
else
    if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
        echo "The Mac's part of the test has to be run on a Mac with an Apple chip: run this there. stable stays where it is." >&2
        exit 1
    fi
    LOG="$(mktemp)"
    echo "Testing on this Mac: each part by itself (a minute)..."
    if ! sh tools/test.sh --at "$NEW" >"$LOG" 2>&1; then
        grep -v '^ *$' "$LOG" | tail -30 >&2
        note_mac failure "The unit tests did not pass on a Mac (tools/test.sh, run by tools/release.sh)" || true
        echo "The unit tests did not pass on this Mac (all of what they said: $LOG). stable stays where it is." >&2
        exit 1
    fi
    echo "Testing on this Mac: installed and used, in an empty home (about a minute)..."
    if sh tools/try_here.sh "$NEW" >"$LOG" 2>&1; then
        note_mac success "Unit tests passed; installed and used on a Mac (tools/test.sh and tools/try_here.sh, run by tools/release.sh)"
        echo "The Mac: passed."
        rm -f "$LOG"
    else
        grep -v '^ *$' "$LOG" | tail -30 >&2
        note_mac failure "Did not pass on a Mac (tools/try_here.sh, run by tools/release.sh)" || true
        echo "The test did not pass on this Mac (all of what it said: $LOG). stable stays where it is." >&2
        exit 1
    fi
fi

if [ "$END" != "success" ]; then
    echo "Waiting for Linux and Windows on GitHub..."
    gh run watch "$ID" --repo "$REPO" --interval 20 --exit-status >/dev/null 2>&1 || true
    look
fi
if [ "$END" != "success" ]; then
    echo "The test on GitHub did not pass at this version (it ended: ${END:-not at all}). stable stays where it is." >&2
    [ -n "$ID" ] && echo "    gh run view $ID --repo $REPO --log-failed" >&2
    exit 1
fi
echo "Linux and Windows: passed."

git push -q origin "$NEW:refs/heads/stable" || {
    echo "GitHub refused to move stable (it requires the three checks to have passed at this version). stable stays where it is." >&2
    exit 1
}
echo "Done: stable is now at $(git log -1 --format='%h %s' "$NEW"). The page will offer it to everyone within six hours, or the next time they open it."
