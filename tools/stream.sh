#!/bin/sh
# Starts the live map viewer and a capture; runs until stop_stream.sh, Ctrl-C or DURATION_S. Works from any directory.
#   sh tools/stream.sh [DURATION_S=0] [RECORD_NAME]    env: LOOPS, PERIOD_MS (defaults from config.toml), FLIP=1 (mirror azimuth), BG=0 (no background subtraction), DRY=1
#   RECORD_NAME records the muxed 16-RX frames to captures/<name>/; a name starting with KEEP_ also keeps the SSD original.
ROOT=$(cd "$(dirname "$0")/.." && pwd) || exit 1
cd "$ROOT" || exit 1
WD=$(pwd -W 2>/dev/null || pwd)
C() { python tools/cfg.py "$1"; }
PY=$(C pc.python); PORT1=$(C pc.ports | cut -d' ' -f1); PORTS_RE=":$(C pc.ports | sed 's/ /|:/g') "
LOOPS=${LOOPS:-$(C capture.loops)}; IFI=${PERIOD_MS:-$(C capture.period_ms)}; DUR=${1:-0}; RECORD=${RECORD:-$2}
LOCK="$ROOT/logs/stream.running"; STOP="$ROOT/logs/stream.stop"
mkdir -p logs
RECARG=""; [ -n "$RECORD" ] && RECARG="--record-capture $RECORD"
FLIPARG=""; [ "${FLIP:-0}" = 1 ] && FLIPARG="--flip-azimuth"
BGARG="--background"; [ "${BG:-1}" = 0 ] && BGARG=""
VARGS="--loops $LOOPS --period-ms $IFI --eta 30 --arrival-log logs/arrivals.csv $RECARG $FLIPARG $BGARG"
if [ "${DRY:-0}" = 1 ]; then
  echo "DRY=1: would start the viewer: \"$PY\" tools/live_maps.py $VARGS"
  echo "       then the capture: LOOPS=$LOOPS PERIOD_MS=$IFI sh tools/run_capture.sh $DUR $RECORD"
  DRY=1 LOOPS=$LOOPS PERIOD_MS=$IFI sh tools/run_capture.sh "$DUR" "$RECORD"; exit $?
fi
if netstat -ano | grep -qE "($PORTS_RE).*LISTEN"; then echo "!! the listener ports are in use (a viewer is still running): sh tools/stop_stream.sh --close-viewer"; exit 3; fi
[ -f "$LOCK" ] && { echo "!! a stream is already running ($(cat "$LOCK")); sh tools/stop_stream.sh first (or --force if no stream.sh is alive)"; exit 3; }
TS=$(date +%Y%m%d_%H%M%S)
rm -f logs/viewer.quit "$STOP"
echo "starting $TS" > "$LOCK"
cleanup() { rm -f "$LOCK" "$STOP"; }
trap 'echo "-- Ctrl-C: stopping the stream cleanly ..."; touch "$STOP"' INT TERM
trap 'cleanup' EXIT

sh tools/studio_cmd.sh start > /dev/null || { echo "!! Studio bridge could not start (is Studio open with its Lua server listening?)"; exit 4; }
sh tools/studio_cmd.sh "dofile(\"$WD/lua/harness.lua\")" > /dev/null
sh tools/studio_cmd.sh "set_mirror_log(\"$WD/logs/stream_studio.txt\")" > /dev/null
sh tools/studio_cmd.sh "run_logged(\"$WD/lua/Cascade_StopCapture.lua\")" 60 > /dev/null
PRE=$(awk '/### run_logged BEGIN .*Cascade_StopCapture/{buf=""} {buf=buf $0 "\n"} END{printf "%s", buf}' logs/stream_studio.txt | grep -cE "Stop Frame Successful")
echo "-- pre-flight: framing stopped on $PRE device(s) that were still running, recording stopped"

"$PY" tools/live_maps.py $VARGS > "logs/viewer_$TS.txt" 2>&1 &
sleep 5
VPID=$(netstat -ano | grep -E ":$PORT1 .*LISTEN" | awk '{print $NF}' | head -1)
[ -z "$VPID" ] && { echo "!! the viewer did not open port $PORT1; see logs/viewer_$TS.txt"; exit 3; }
echo "$VPID" > logs/stream_viewer.pid
echo "== stream: viewer pid $VPID, ${IFI} ms x ${LOOPS} loop(s), record=${RECORD:-no}, duration=${DUR} s (0 = until stop_stream.sh / Ctrl-C)"

LOOPS=$LOOPS PERIOD_MS=$IFI sh tools/run_capture.sh "$DUR" "$RECORD" > logs/stream_runner.txt 2>&1 &
RPID=$!
tail -n +1 -f logs/stream_runner.txt 2>/dev/null | grep --line-buffered -E "^(>>>|!!|--)" &
TPID=$!
( n=0; while [ $n -lt 150 ] && ! grep -q "^>>> STREAMING" logs/stream_runner.txt 2>/dev/null; do sleep 1; n=$((n + 1)); [ -f "$STOP" ] && exit 0; kill -0 $RPID 2>/dev/null || exit 0; done
  grep -q "^>>> STREAMING" logs/stream_runner.txt 2>/dev/null || exit 0
  n=0; while [ $n -lt 40 ]; do [ "$(wc -l < logs/arrivals.csv 2>/dev/null || echo 0)" -gt 5 ] && exit 0; sleep 1; n=$((n + 1)); [ -f "$STOP" ] && exit 0; done
  echo "!! LIVE WATCHDOG: the runner reached STREAMING but no frame reached the viewer within 40 s"
  CONN=$(grep -c "connection from" "logs/viewer_$TS.txt" 2>/dev/null)
  DIR=$(cat "$LOCK" 2>/dev/null)
  BOARD=$(sh tools/tda2_ssh.sh "ps | grep -v grep | grep -c follow_slot.py; dd if=$(C tda.ssd)/$DIR/master_0000_data.bin bs=4096 skip=11 count=1 2>/dev/null | tr -d '\000' | wc -c" 2>/dev/null | tr '\n' ' ')
  set -- $BOARD; FOLL=${1:-?}; BYTES=${2:-?}
  echo "   followers connected to the viewer: $CONN of 4 | follower processes on the board: $FOLL | non-zero bytes in frame slot 0 on the SSD: $BYTES"
  if [ "$BYTES" = 0 ]; then
    echo "   => the TDA is NOT writing frames (bad boot). Stopping. Next: power-cycle the board with Studio open, wait 3 min, sh tools/connect.sh, sh tools/stream.sh"
    touch "$STOP"
  elif [ "$CONN" -lt 4 ] || [ "$FOLL" -lt 4 ]; then
    echo "   => frames are on the SSD but the followers are not all connected. Stopping. Next: sh tools/stop_stream.sh --force, then sh tools/stream.sh again"
    touch "$STOP"
  else
    echo "   => followers connected and frames on the SSD but the viewer shows nothing: see logs/viewer_$TS.txt; sh tools/stop_stream.sh --close-viewer, then sh tools/stream.sh"
  fi ) &
WPID=$!
while kill -0 $RPID 2>/dev/null; do wait $RPID; done
kill $TPID $WPID 2>/dev/null

verify() { awk '/### run_logged BEGIN .*Cascade_StopCapture/{buf=""} {buf=buf $0 "\n"} END{printf "%s", buf}' logs/stream_studio.txt | grep -cE "verified stopped"; }
n=$(verify)
if [ "$n" -lt 4 ]; then
  echo "!! stop not verified on all devices ($n of 4): forcing a second stop"
  sh tools/studio_cmd.sh "run_logged(\"$WD/lua/Cascade_StopCapture.lua\")" 60 > /dev/null; n=$(verify)
fi
if [ "$n" -ge 4 ]; then echo "== stream ended: framing verified stopped on 4 devices, recording stopped"; else echo "!! STOP NOT VERIFIED ($n of 4): check Studio, do not start a new stream"; fi
grep -E "^!!" logs/stream_runner.txt | head -3
echo "   viewer still open (pid $VPID): close its window or sh tools/stop_stream.sh --close-viewer"
