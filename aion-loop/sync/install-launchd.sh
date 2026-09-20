#!/bin/bash
# Install / reload the AION Control Sync launchd agent (user level, V1).
# Run by ILYAR (Claude is denied launchctl/cron by the lock — by design):
#     bash <AION_ROOT>/sync/install-launchd.sh
# Safe to re-run: it reloads the service. Touches ONLY com.aion.control-sync.
set -eu
LABEL="com.aion.control-sync"
SRC="<AION_ROOT>/sync/$LABEL.plist"
DST="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_="$(id -u)"

plutil -lint "$SRC" >/dev/null
mkdir -p "$HOME/Library/LaunchAgents" "<AION_ROOT>/.sync"
cp -f "$SRC" "$DST"
chmod 644 "$DST"

# unload if already loaded (ignore error if not), then load fresh
launchctl bootout "gui/$UID_/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_" "$DST"
launchctl enable "gui/$UID_/$LABEL"
launchctl kickstart -k "gui/$UID_/$LABEL"

echo "installed: $DST"
launchctl print "gui/$UID_/$LABEL" | grep -E 'state|last exit code|runs|pid' | head -6
echo "log: <HOME>/.aion-control-sync/sync.log"
