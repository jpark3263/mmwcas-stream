#!/bin/bash
# Unattended soak: 10 start/stop cycles (two batches of 5), a 30-minute stream, a 10-minute stream with recording; summary by soak_summary.py. DRY=1 prints the plan.
#   sh extras/soak.sh      precondition: this boot is connected (tools/connect.sh) and a short stream came up LIVE
set -m
ROOT=$(cd "$(dirname "$0")/.." && pwd) || exit 1; cd "$ROOT" || exit 1
TS=$(date +%Y%m%d_%H%M%S); OUT="$ROOT/logs/soak_$TS"; mkdir -p "$OUT"
RAM_MIN_MB=${RAM_MIN_MB:-1200}
PORT1=$(python tools/cfg.py pc.ports | cut -d' ' -f1)
RSTD=$(ls -t "$APPDATA/RSTD/Output/Log/"Log*_0.txt | head -1)
log() { echo "$(date +%H:%M:%S) $*" | tee -a "$OUT/soak.log"; }
ram_mb() { python -c "import psutil; print(int(psutil.virtual_memory().available/1e6))" 2>/dev/null || echo 99999; }
wait_ram() { while [ "$(ram_mb)" -lt "$RAM_MIN_MB" ]; do log "!! RAM pressure: $(ram_mb) MB available (< $RAM_MIN_MB): pausing 30 s"; sleep 30; done; }
sentinels() { awk -v s="$1" 'NR>s' "$RSTD" | grep -a -E "TDA Stop Record ACK not received|RESP TIMEOUT|Failed" | grep -a -vE "frames already stopped|FRAME ARE ALREADY STOPPED WHEN THE FRAME_STOP" | head -3; }
snapshot() {
  mkdir -p "$OUT/$1/idx"
  cp logs/stream_*.txt logs/stream_cycle_*.txt logs/stop_cycle_*.txt logs/arrivals.csv logs/soak_monitor_*.csv "$OUT/$1/" 2>/dev/null
  ls -t logs/viewer_*.txt | head -${2:-5} | xargs -I{} cp {} "$OUT/$1/" 2>/dev/null
  DIR=$(cat logs/last_capture_dir.txt 2>/dev/null); echo "$DIR" > "$OUT/$1/capture_dir.txt"
  cp logs/runs/$DIR/*_idx.bin "$OUT/$1/idx/" 2>/dev/null; cp logs/runs/$DIR/follow_master.log "$OUT/$1/" 2>/dev/null
}
finish() { rm -f "$PIDFILE"; python extras/soak_summary.py "$OUT" > "$OUT/SUMMARY.txt" 2>&1; echo; cat "$OUT/SUMMARY.txt"; log "== soak finished: $OUT/SUMMARY.txt"; exit ${1:-0}; }
log "== soak start; logs in $OUT; RAM $(ram_mb) MB available; Studio log $RSTD"
[ "${DRY:-0}" = 1 ] && { log "DRY=1: stages = cycles 5+5 (gaps 10/120/600) -> stream 1800 s (monitor 60 s) -> stream 600 s RECORD=KEEP_soak -> summary"; exit 0; }
PIDFILE="$ROOT/logs/soak.pid"
for pf in "$ROOT/logs/soak.pid" "$ROOT/logs/soak_cycles.pid"; do
  if [ -f "$pf" ] && kill -0 "$(cat "$pf" 2>/dev/null)" 2>/dev/null; then log "!! another harness is running: $(basename "$pf" .pid) pid $(cat "$pf"): kill it first, then sh tools/stop_stream.sh --close-viewer"; exit 3; fi
done
echo $$ > "$PIDFILE"; trap 'rm -f "$PIDFILE"' EXIT
[ -f logs/stream.running ] && { log "!! a stream is already running ($(cat logs/stream.running)); sh tools/stop_stream.sh first"; exit 3; }
netstat -ano | grep -qE ":$PORT1 .*LISTEN" && { log "!! the listener ports are busy (viewer open): sh tools/stop_stream.sh --close-viewer first"; exit 3; }

L0=$(wc -l < "$RSTD")
attempt=1
while [ $attempt -le 2 ]; do
  log "== stage 1: 10 cycles, attempt $attempt (batch A: cycles 1-5, batch B: cycles 6-10)"
  ok=1
  for batch in A B; do
    wait_ram
    mkdir -p "$OUT/cycles_${attempt}${batch}"
    if [ $batch = A ]; then GAPS="10 120 600"; else GAPS="120 600 10"; fi
    bash extras/soak_cycles.sh 5 "$GAPS" 60 2>&1 | tee -a "$OUT/soak.log" | grep -E "^(cycle|!!|==|   gap)" | sed "s/^cycle \([0-9]\)/cycle ${batch}\1/"
    rc=${PIPESTATUS[0]}
    snapshot "cycles_${attempt}${batch}" 6
    if [ $rc -ne 0 ]; then ok=0; log "!! batch $batch failed (see $OUT/cycles_${attempt}${batch} and logs/soakfail_*)"; break; fi
    [ $batch = A ] && { log "   batch pause 600 s"; sleep 600; }
  done
  S=$(sentinels $L0); [ -n "$S" ] && { log "!! SENTINEL in Studio log: $S"; finish 2; }
  [ $ok = 1 ] && break
  attempt=$((attempt + 1)); [ $attempt -le 2 ] && log "-- restarting the 10-cycle count from zero" && sleep 30
done
[ $ok = 1 ] || { log "!! stage 1 failed twice: soak stopped (radar left stopped)"; finish 1; }

wait_ram; L1=$(wc -l < "$RSTD"); mkdir -p "$OUT/stream30"
log "== stage 2: 30-minute stream (viewer on, no recording, monitor rows every 60 s)"
python extras/soak_monitor.py --interval 60 > "$OUT/stream30/monitor_console.txt" 2>&1 &
sh tools/stream.sh 1800 2>&1 | tee "$OUT/stream30/stream_console.txt" | grep -E "^(==|!!|>>>)"
sh tools/stop_stream.sh --close-viewer >/dev/null 2>&1
snapshot stream30 2
grep -q "^!! LIVE WATCHDOG" "$OUT/stream30/stream_console.txt" && { log "!! stage 2: the LIVE watchdog fired (bad boot): soak stopped"; finish 2; }
S=$(sentinels $L1); [ -n "$S" ] && { log "!! SENTINEL in Studio log: $S"; finish 2; }
log "-- stage 2 done: $(( $(wc -l < logs/arrivals.csv) - 1 )) frames at the viewer"

wait_ram; L2=$(wc -l < "$RSTD"); mkdir -p "$OUT/record10"
FREE_GB=$(python -c "import psutil,os; print(int(psutil.disk_usage(os.getcwd()).free/1e9))" 2>/dev/null || echo 99)
[ "$FREE_GB" -lt 10 ] && { log "!! only $FREE_GB GB free on this drive; the 10-min recording needs ~6 GB: stage 3 skipped"; finish 0; }
log "== stage 3: 10-minute stream with RECORD=KEEP_soak (~5.9 GB, $FREE_GB GB free)"
rm -rf captures/KEEP_soak
python extras/soak_monitor.py --interval 60 > "$OUT/record10/monitor_console.txt" 2>&1 &
RECORD=KEEP_soak sh tools/stream.sh 600 2>&1 | tee "$OUT/record10/stream_console.txt" | grep -E "^(==|!!|>>>)"
sh tools/stop_stream.sh --close-viewer >/dev/null 2>&1
snapshot record10 2; cp captures/KEEP_soak/config.json captures/KEEP_soak/frames.csv "$OUT/record10/" 2>/dev/null
grep -q "^!! LIVE WATCHDOG" "$OUT/record10/stream_console.txt" && { log "!! stage 3: the LIVE watchdog fired: soak stopped"; finish 2; }
S=$(sentinels $L2); [ -n "$S" ] && { log "!! SENTINEL in Studio log: $S"; finish 2; }
log "-- stage 3 done"
finish 0
