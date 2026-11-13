#!/bin/sh
# Give people the newest version: move the branch "stable" on to where "main" is.
#
#     sh tools/release.sh            look, test if need be, and move it
#     sh tools/release.sh --look     only say what would be given out
#
# Everyone's install line, and the "Update now" button on the page, take the newest version on "stable".  Work is
# pushed to "main" as it goes, so "stable" is what stands between a half-finished change and a singer's computer.
# This moves it only to a version that the test on GitHub ("installs and sings": the real installer and
# tools/try_install.py on Linux, Windows and a Mac) has passed, at exactly that version.  If the test has not been
# run there - a change to the documents alone does not start it - it is started here and waited for.
#
# GitHub holds to the same rule by itself: "stable" is a protected branch that requires the three checks (Linux,
# Windows, Mac), for the owner too.  A push to it by hand of a version that has not passed them is refused.
#
# It needs git, and gh signed in to an account that may push to the repository.
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
    if [ -z "$ID" ] || [ "$STATUS" = "completed" ]; then           # never run here, or it did not pass: run it (again)
        echo "Starting the test on Linux, Windows and a Mac at $(git rev-parse --short "$NEW")..."
        was="$ID"
        gh workflow run "$TEST" --repo "$REPO" --ref main >/dev/null
        tries=0
        while :; do
            sleep 5; look
            [ -n "$ID" ] && [ "$ID" != "$was" ] && break
            tries=$((tries + 1)); [ "$tries" -lt 24 ] || { echo "The test did not start. Look at the Actions page of the repository." >&2; exit 1; }
        done
    fi
    echo "Waiting for the test (GitHub's Mac machines can take a while to come free)..."
    gh run watch "$ID" --repo "$REPO" --interval 30 --exit-status >/dev/null 2>&1 || true
    look
fi
if [ "$END" != "success" ]; then
    echo "The test did not pass at this version (it ended: ${END:-not at all}). stable stays where it is." >&2
    [ -n "$ID" ] && echo "    gh run view $ID --repo $REPO --log-failed" >&2
    exit 1
fi

git push -q origin "$NEW:refs/heads/stable" || {
    echo "GitHub refused to move stable (it requires the three checks to have passed at this version). stable stays where it is." >&2
    exit 1
}
echo "Done: stable is now at $(git log -1 --format='%h %s' "$NEW"). The page will offer it to everyone within six hours, or the next time they open it."
