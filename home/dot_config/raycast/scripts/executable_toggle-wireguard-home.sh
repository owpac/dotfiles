#!/usr/bin/env bash
set -euo pipefail

# Raycast Script Command — one-press toggle for the "home" WireGuard tunnel.
#
# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Toggle WireGuard: Home
# @raycast.mode silent
#
# Optional parameters:
# @raycast.icon 🔐
# @raycast.packageName Network
#
# Documentation:
# @raycast.description Toggle the home WireGuard tunnel (official app)
# @raycast.author thomas
#
# Feedback is a Raycast HUD (silent mode shows stdout), so we just echo one line.

TUNNEL="home"

is_connected() { [ "$(scutil --nc status "$1" | head -1)" = "Connected" ]; }
tunnel_exists() { scutil --nc list | grep 'com.wireguard.macos' | grep -qF "\"$1\""; }

if ! tunnel_exists "$TUNNEL"; then
    echo "VPN tunnel not found — $TUNNEL ⚠️"
    exit 0
fi

if is_connected "$TUNNEL"; then
    scutil --nc stop "$TUNNEL"
    echo "VPN off — $TUNNEL 🔴"
    exit 0
fi

scutil --nc start "$TUNNEL"
for _ in 1 2 3 4 5 6 7 8 9 10; do
    is_connected "$TUNNEL" && break
    sleep 0.5
done
if is_connected "$TUNNEL"; then
    echo "VPN connected — $TUNNEL 🟢"
else
    echo "VPN connecting… — $TUNNEL 🟡"
fi
