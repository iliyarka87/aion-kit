#!/bin/bash
# Remove the AION Control Sync launchd agent. Touches ONLY com.aion.control-sync.
set -eu
LABEL="com.aion.control-sync"
DST="$HOME/Library/LaunchAgents/$LABEL.plist"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$DST"
echo "removed: $DST"
