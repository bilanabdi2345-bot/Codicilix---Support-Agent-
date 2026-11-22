#!/bin/bash
# Puts this combined version of Codicilix into the team repo on GitHub
# (github.com/bilanabdi2345-bot/Codicilix---Support-Agent-), runs the tests, and pushes.
# After this, the Codicilix app and "Update Codicilix" use this repo.
#
# Run it in Terminal:   bash ~/Downloads/<this folder>/scripts/push-to-github.sh

set -e
SRC="$(cd "$(dirname "$0")/.." && pwd)"
REPO_URL="${TEAM_REPO_URL:-https://github.com/bilanabdi2345-bot/Codicilix---Support-Agent-.git}"
DEST="$HOME/Downloads/Codicilix"

say() { printf "\n\033[1m%s\033[0m\n" "$1"; }

# Safety stops, so nothing is copied to the wrong place.
[ -f "$SRC/secondbrain/__main__.py" ] || {
  echo "Safety stop: run this from inside the unzipped team version of Codicilix."; exit 1; }

say "1. Getting the team repo..."
if [ ! -d "$DEST/.git" ]; then
  git clone "$REPO_URL" "$DEST"
fi
cd "$DEST"
git remote get-url origin | grep -q "Codicilix---Support-Agent-" || {
  echo "Safety stop: $DEST is not the team repo."; exit 1; }
git checkout -q main
git pull -q --ff-only || { echo "Safety stop: the team repo has changes I can't merge automatically. Send this message to Claude."; exit 1; }

say "2. Copying in the newest Codicilix..."
rsync -a --delete --exclude .git --exclude bin --exclude .DS_Store --exclude __pycache__ "$SRC/" "$DEST/"

say "3. Running the tests..."
python3 -B -m unittest discover -s tests || { echo; echo "Tests failed, so nothing was pushed. Send the message above to Claude."; exit 1; }

say "4. Saving and pushing to GitHub..."
git add -A
if git diff --cached --quiet; then
  echo "Nothing new to push."
else
  git commit -q -F - <<'MSG'
Codicilix: the best of Bilan's and David's versions

Bilan's: handwriting, photos and screenshots, pasted pictures, the photo
viewer, Word/Excel/PDF with comments and markings, the shield against
hidden instructions, themes, the app window and the model picker.
David's: what changed, what I owe, the decision log, private notes, and
answers that still work without the AI.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VVwckBErnYPaqTrkmwxFR8
MSG
  git push origin main
fi

say "5. Rebuilding the Codicilix app from the team repo..."
QUIET=1 bash scripts/make-mac-app.sh || echo "Couldn't rebuild the app. The push still worked."

say "Done. GitHub is up to date: https://github.com/bilanabdi2345-bot/Codicilix---Support-Agent-"
