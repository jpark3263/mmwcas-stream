#!/bin/sh
# Stops a stream started by stream.sh: framing on the four devices (verified) and the TDA recording. Works from any directory.
#   sh tools/stop_stream.sh                 signal the running stream.sh
#   sh tools/stop_stream.sh --close-viewer  ... and close the map window (the recording is flushed first)
#   sh tools/stop_stream.sh --force         no stream.sh alive: send the stop script to Studio directly, stop the board followers, clear the lock
ROOT=$(cd "$(dirname "$0")/.." && pwd) || exit 1
cd "$ROOT" || exit 1
WD=$(pwd -W 2>/dev/null || pwd)
PORT1=$(python tools/cfg.py pc.ports | cut -d' ' -f1)
LOCK="$ROOT/logs/stream.running"; STOP="$ROOT/logs/stream.stop"
FORCE=0; CLOSE=0
for arg in "$@"; do
  case "$arg" in --force) FORCE=1 ;; --close-viewer) CLOSE=1 ;; *) echo "usage: sh tools/stop_stream.sh [--close-viewer] [--force]"; exit 2 ;; esac
done
if [ "${DRY:-0}" = 1 ]; then
  echo "DRY=1: would touch $STOP and wait up to 90 s for stream.sh to confirm; --force would run $WD/lua/Cascade_StopCapture.lua in Studio, sh /tmp/stop_followers.sh on the board and clear the lock; --close-viewer would touch logs/viewer.quit"
  exit 0
fi
force_stop() {
  echo "-- sending lua/Cascade_StopCapture.lua to Studio directly"
  sh tools/studio_cmd.sh start > /dev/null 2>&1
  sh tools/studio_cmd.sh "run_logged(\"$WD/lua/Cascade_StopCapture.lua\")" 60 | head -1 | sed 's/^/   /'
  sh tools/tda2_ssh.sh "sh /tmp/stop_followers.sh" 2>/dev/null | tail -1
  rm -f "$LOCK" "$STOP"
  echo "-- forced stop done (lock cleared)"
}
if [ $FORCE = 1 ]; then
  force_stop
elif [ ! -f "$LOCK" ]; then
  echo "-- no stream.sh is running. Use --force to stop the radar anyway."
else
  touch "$STOP"
  echo "-- stop requested ($(cat "$LOCK")); waiting for stream.sh to stop framing and the recording ..."
  n=0; while [ -f "$LOCK" ] && [ $n -lt 90 ]; do sleep 1; n=$((n + 1)); done
  if [ -f "$LOCK" ]; then echo "!! stream.sh did not confirm within 90 s: forcing"; force_stop; else echo "-- stopped (verified by stream.sh)"; fi
fi
if [ $CLOSE = 1 ]; then
  if netstat -ano | grep -qE ":$PORT1 .*LISTEN"; then
    touch "$ROOT/logs/viewer.quit"
    n=0; while [ $n -lt 10 ] && netstat -ano | grep -qE ":$PORT1 .*LISTEN"; do sleep 1; n=$((n + 1)); done
    if netstat -ano | grep -qE ":$PORT1 .*LISTEN"; then
      P=$(netstat -ano | grep -E ":$PORT1 .*LISTEN" | awk '{print $NF}' | head -1); [ -n "$P" ] && taskkill //PID $P //F > /dev/null 2>&1 && echo "-- viewer killed (did not quit by itself)"
    else
      echo "-- viewer closed"
    fi
    rm -f "$ROOT/logs/viewer.quit"
  else
    echo "-- no viewer running"
  fi
fi
rm -f "$ROOT/logs/stream_viewer.pid"
