#!/bin/sh
# Quit Adaptalux.app (so it disconnects from the pods cleanly) and open it again.
# Build the app first with scripts/make-app.sh.

app="$HOME/Applications/Adaptalux.app"
match="adaptalux_control.gui import main"

if pgrep -f "$match" >/dev/null; then
    # The window puts off the quit until it has disconnected, which osascript reports as
    # "User canceled"; the app still exits on its own a moment later.
    osascript -e 'quit app "Adaptalux"' 2>/dev/null || true
    # Give it up to 10 s to disconnect and exit.
    i=0
    while pgrep -f "$match" >/dev/null && [ $i -lt 20 ]; do
        sleep 0.5
        i=$((i + 1))
    done
    if pgrep -f "$match" >/dev/null; then
        echo "Adaptalux did not quit; not starting a second copy" >&2
        exit 1
    fi
fi

open "$app"
echo "Adaptalux started"
