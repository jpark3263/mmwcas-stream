#!/bin/bash
# N start/stop cycles of the live stream on one connect.sh, alternating stop_stream.sh and a real Ctrl-C (SIGINT under job control); verifies every cycle.
#   sh extras/soak_cycles.sh N "gap1 gap2 ..." [STREAM_S=60]
set -m
N=${1:-10}; GAPS=${2:-"10 120 600"}; STREAM_S=${3:-60}
ROOT=$(cd "$(dirname "$0")/.." && pwd) || exit 1; cd "$ROOT" || exit 1
PORT1=$(python tools/cfg.py pc.ports | cut -d' ' -f1)
RSTD=$(ls -t "$APPDATA/RSTD/Output/Log/"Log*_0.txt | head -1)
LOCK="$ROOT/logs/stream.running"
SUMMARY="$ROOT/logs/soak_cycles_$(date +%Y%m%d_%H%M%S).txt"
PIDFILE="$ROOT/logs/soak_cycles.pid"
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null; then echo "!! another soak_cycles.sh (pid $(cat "$PIDFILE")) is running: kill $(cat "$PIDFILE") first"; exit 3; fi
echo $$ > "$PIDFILE"; trap 'rm -f "$PIDFILE"' EXIT
OWN=0
fail() { echo "!! CYCLE $i FAILED: $1" | tee -a "$SUMMARY"; d="$ROOT/logs/soakfail_$i"; mkdir -p "$d"; cp logs/stream_*.txt logs/stream_cycle_$i.txt "$d/" 2>/dev/null; ls -t logs/viewer_*.txt | head -1 | xargs -I{} cp {} "$d/" 2>/dev/null; tail -300 "$RSTD" > "$d/studio_tail.txt"
  sh tools/tda2_ssh.sh "ls -l $(python tools/cfg.py tda.ssd)/$(cat $LOCK 2>/dev/null || cat logs/last_capture_dir.txt)/ 2>&1; ps | grep -v grep | grep -E 'follow|apps'; tail -3 /tmp/follow_master.log 2>/dev/null" > "$d/board.txt" 2>&1
  if [ $OWN = 1 ]; then sh tools/stop_stream.sh --close-viewer --force >/dev/null 2>&1; else echo "   our stream.sh never reached STREAMING -> not touching the radar/viewer (lock='$(cat $LOCK 2>/dev/null)')"; fi
  echo "   logs kept in $d"; exit 1; }
sentinel() { awk -v s="$1" 'NR>s' "$RSTD" | grep -a -E "TDA Stop Record ACK not received|RESP TIMEOUT|Failed" | grep -a -vE "frames already stopped|FRAME ARE ALREADY STOPPED WHEN THE FRAME_STOP" | head -3; }
alive() { kill -0 "$1" 2>/dev/null; }
last_stop_block() { awk '/### run_logged BEGIN .*Cascade_StopCapture/{buf=""} {buf=buf $0 "\n"} END{printf "%s", buf}' logs/stream_studio.txt; }
echo "== soak cycles: N=$N gaps='$GAPS' stream=${STREAM_S}s, Studio log $RSTD" | tee "$SUMMARY"
i=1
while [ $i -le $N ]; do
  L0=$(wc -l < "$RSTD")
  T0=$(date +%H:%M:%S)
  rm -f logs/arrivals.csv
  sh tools/stream.sh 0 > logs/stream_cycle_$i.txt 2>&1 &
  SPID=$!
  echo "   cycle $i: stream.sh started (pid $SPID)"
  n=0; while [ $n -lt 150 ] && ! grep -q "^mmwcas_" "$LOCK" 2>/dev/null; do sleep 1; n=$((n + 1)); alive $SPID || break; done
  grep -q "^mmwcas_" "$LOCK" 2>/dev/null || fail "stream.sh did not reach STREAMING in $n s ($(head -c 200 logs/stream_cycle_$i.txt | tr '\n' ' '))"
  OWN=1; T_STREAM=$n
  n=0; while [ $n -lt 40 ] && [ "$(wc -l < logs/arrivals.csv 2>/dev/null || echo 0)" -le 5 ]; do sleep 1; n=$((n + 1)); done
  [ $n -ge 40 ] && fail "no frames at the viewer within 40 s of STREAMING (LIVE watchdog case)"
  T_LIVE=$n
  DIR=$(cat "$LOCK")
  sleep $STREAM_S
  if [ $((i % 2)) = 1 ]; then
    METHOD=stop_stream; sh tools/stop_stream.sh --close-viewer > logs/stop_cycle_$i.txt 2>&1
  else
    METHOD=ctrl-c; kill -INT $SPID || fail "could not send SIGINT to pid $SPID"
    n=0; while [ -f "$LOCK" ] && [ $n -lt 90 ]; do sleep 1; n=$((n + 1)); done
    [ -f "$LOCK" ] && fail "Ctrl-C did not stop the stream within 90 s (lock still present)"
    sh tools/stop_stream.sh --close-viewer >> logs/stop_cycle_$i.txt 2>&1
  fi
  n=0; while alive $SPID && [ $n -lt 120 ]; do sleep 1; n=$((n + 1)); done
  alive $SPID && fail "stream.sh (pid $SPID) still alive 120 s after the stop"
  sleep 3
  STOPPED=$(last_stop_block | grep -c "Stop Frame Successful")
  VERIF=$(last_stop_block | grep -c "verified stopped")
  PORTS=$(netstat -ano | grep -cE ":$PORT1 .*LISTEN"); BOARD=$(sh tools/tda2_ssh.sh "ps | grep -v grep | grep -cE 'follow_slot|start_followers'")
  LOCKS=$(ls logs/stream.running logs/stream.stop 2>/dev/null | wc -l)
  FRAMES=$(( $(wc -l < logs/arrivals.csv) - 1 ))
  ENDED=$(grep -c "== stream ended: framing verified stopped on 4 devices" logs/stream_cycle_$i.txt)
  SENT=$(sentinel $L0)
  TDA=$(python extras/run_summary.py "$DIR" 2>/dev/null | sed -E 's/.*idx ([0-9]+) frames, dt median ([0-9.]+) ms \(min ([0-9.]+) max ([0-9.]+)\).*/\1 fr, dt \2 ms, max gap \4 ms/')
  echo "cycle $i | $T0 | STREAMING +${T_STREAM}s, LIVE +${T_LIVE}s | ${STREAM_S}s | stop=$METHOD | StopFrame $STOPPED/4, verified $VERIF/4, stream.sh verified-line $ENDED | PC frames $FRAMES | TDA: $TDA | ports $PORTS board $BOARD locks $LOCKS" | tee -a "$SUMMARY"
  [ -n "$SENT" ] && fail "sentinel in Studio log: $SENT"
  [ "$STOPPED" = 0 ] && [ "$VERIF" = 4 ] && fail "the radar was ALREADY stopped when our stop ran ($FRAMES frames only): another harness or a self-stop"
  [ "$STOPPED" = 4 ] && [ "$VERIF" = 4 ] && [ "$ENDED" = 1 ] || fail "stop not verified ($STOPPED stopped, $VERIF verified, stream.sh line $ENDED)"
  [ "$PORTS" = 0 ] && [ "$BOARD" = 0 ] && [ "$LOCKS" = 0 ] || fail "not clean after stop (ports $PORTS board $BOARD locks $LOCKS)"
  if [ $i -lt $N ]; then set -- $GAPS; gi=$(( (i - 1) % $# )); k=0; for g in "$@"; do [ $k = $gi ] && GAP=$g; k=$((k + 1)); done; echo "   gap ${GAP}s" | tee -a "$SUMMARY"; sleep $GAP; fi
  i=$((i + 1))
done
echo "== all $N cycles passed" | tee -a "$SUMMARY"
