#!/usr/bin/env bash
# Virtual display + window manager + VNC + browser-based viewer (noVNC), then the given command
set -e
export DISPLAY=:99
Xvfb :99 -screen 0 1280x800x24 -nolisten tcp >/dev/null 2>&1 &
sleep 1
fluxbox >/dev/null 2>&1 &
x11vnc -display :99 -forever -shared -nopw -localhost -rfbport 5900 -quiet >/dev/null 2>&1 &
websockify --web /usr/share/novnc 6080 localhost:5900 >/dev/null 2>&1 &
echo "Direct-run screen: http://${JAMIE_HOST:-localhost}:6080/vnc.html (controller sessions use the dashboard link)"
if [ $# -gt 0 ]; then exec "$@"; else exec sleep infinity; fi
