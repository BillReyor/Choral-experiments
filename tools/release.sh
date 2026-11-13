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

# the newest run of the test at exactly this version: its id and how it ended
newest() { gh run list --repo "$REPO" --workflow "$TEST" --commit "$NEW" --limit 1 --json databaseId,status,conclusion -q '.[0] | "\(.databaseId) \(.status) \(.conclusion)"' 2>/dev/null || true; }

set -- $(newest)
if [ "${3:-}" != "success" ]; then
    if [ -z "${1:-}" ] || [ "${2:-}" = "completed" ]; then        # never run here, or it did not pass: run it (again)
        echo "Starting the test on Linux, Windows and a Mac at $(git rev-parse --short "$NEW")..."
        gh workflow run "$TEST" --repo "$REPO" --ref main >/dev/null
        tries=0
        while :; do
            sleep 5; set -- $(newest)
            [ -n "${1:-}" ] && [ "${2:-}" != "completed" ] && break
            tries=$((tries + 1)); [ "$tries" -lt 24 ] || { echo "The test did not start. Look at the Actions page of the repository." >&2; exit 1; }
        done
    fi
    echo "Waiting for the test (GitHub's Mac machines can take a while to come free)..."
    gh run watch "$1" --repo "$REPO" --interval 30 --exit-status >/dev/null 2>&1 || true
    set -- $(newest)
fi
if [ "${3:-}" != "success" ]; then
    echo "The test did not pass at this version (it ended: ${3:-not at all}). stable stays where it is." >&2
    echo "    gh run view ${1:-} --repo $REPO --log-failed" >&2
    exit 1
fi

git push -q origin "$NEW:refs/heads/stable"
echo "Done: stable is now at $(git log -1 --format='%h %s' "$NEW"). The page will offer it to everyone within six hours, or the next time they open it."
