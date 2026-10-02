#!/bin/sh
# Runs one capture: reconfigures the radar, starts the board followers, arms the TDA and starts framing, waits for stop_stream.sh (or DURATION_S), stops framing and fetches the idx files.
#   sh tools/run_capture.sh [DURATION_S=0] [NAME]      env: LOOPS, PERIOD_MS (defaults from config.toml), DRY=1 (print the plan only)
#   NAME becomes part of the SSD directory mmwcas_<NAME>_<timestamp>; a NAME starting with KEEP_ is never deleted by ssd_cleanup.py.
ROOT=$(cd "$(dirname "$0")/.." && pwd) || exit 1
cd "$ROOT" || exit 1
WD=$(pwd -W 2>/dev/null || pwd)
C() { python tools/cfg.py "$1"; }
TDA_IP=$(C tda.ip); PC_IP=$(C pc.ip); PORTS=$(C pc.ports); SSD=$(C tda.ssd); MINFREE=$(C tda.free_gb_min)
NICE=$(C follower.nice); POLL=$(C follower.poll_s); SAMPLES=$(C capture.samples); CHIRPS=$(C capture.chirps)
LOOPS=${LOOPS:-$(C capture.loops)}; IFI=${PERIOD_MS:-$(C capture.period_ms)}; DUR=${1:-0}; NAME=$2
TS=$(date +%Y%m%d_%H%M%S); DIR="mmwcas_${NAME:+${NAME}_}$TS"
FB=$((SAMPLES * CHIRPS * LOOPS * 16))
RUN=logs/runs/$DIR; STUDIO_LOG=logs/stream_studio.txt
LOCK=logs/stream.running; STOP=logs/stream.stop
mkdir -p "$RUN" lua/generated
trap '' INT PIPE
export TDA_IP

studio() {
  out=$(sh tools/studio_cmd.sh "$1" "${2:-120}" 2>&1); echo "$out" >> logs/stream_studio_rc.txt
  echo "$out" | grep -q "^RC=0" && return 0
  echo "$out" | grep -qE "^RC=10060|^TIMEOUT" && return 0
  echo "!! Studio command failed: $out"; return 1
}
studio_check() {
  awk '/### run_logged BEGIN/{buf=""} {buf=buf $0 "\n"} END{printf "%s", buf}' "$STUDIO_LOG" > "$RUN/studio_$1.txt"
  if grep -qiE "failed|ok=false" "$RUN/studio_$1.txt"; then echo "!! Studio reported a failure during $1:"; grep -iE "failed|ok=false|error" "$RUN/studio_$1.txt" | head -5; return 1; fi
  echo "   Studio $1 OK: $(grep -c 'uccessful' "$RUN/studio_$1.txt") success lines"
}
board_stop() { sh tools/tda2_ssh.sh "sh /tmp/stop_followers.sh" >> "$RUN/followers.txt" 2>&1; }

echo "== capture $DIR: ${IFI} ms x ${LOOPS} loop(s), frame_bytes/device=$FB, duration=${DUR}s (0 = until stop_stream.sh)  ($(date))"
python tools/make_config.py --loops "$LOOPS" --period-ms "$IFI" --capture-dir "$DIR" --tag "$DIR" > /dev/null || exit 2
RECONF="$WD/lua/generated/Cascade_Reconfig_$DIR.lua"; START="$WD/lua/generated/Cascade_StartCapture_$DIR.lua"; STOPLUA="$WD/lua/Cascade_StopCapture.lua"
if [ "${DRY:-0}" = 1 ]; then
  echo "DRY=1: would (1) check >= $MINFREE GB free on $TDA_IP:$SSD and delete the previous archived run, (2) copy tda2/*.py tda2/*.sh to $TDA_IP:/tmp,"
  echo "       (3) run $RECONF in Studio, (4) start followers: FB=$FB NICE=$NICE POLL=$POLL PORTS='$PORTS' sh /tmp/start_followers.sh $DIR $PC_IP,"
  echo "       (5) run $START, wait for $STOP, run $STOPLUA, (6) fetch $SSD/$DIR/*_idx.bin to $RUN/ and print tools/capture_stats.py"
  rm -rf "$RUN"; exit 0
fi

FREE=$(python tools/ssd_cleanup.py --free 2>/dev/null); FREE=${FREE%.*}
if [ -z "$FREE" ] || [ "$FREE" -lt "$MINFREE" ]; then echo "!! $SSD has ${FREE:-?} GB free (< $MINFREE GB): refusing to start; run python tools/ssd_cleanup.py"; exit 7; fi
PREV=$(cat logs/last_capture_dir.txt 2>/dev/null)
[ -n "$PREV" ] && [ "$PREV" != "$DIR" ] && { echo "-- previous run $PREV:"; python tools/ssd_cleanup.py --dir "$PREV" 2>&1 | grep -E "^(DELETED|keep)"; }
echo "$DIR" > logs/last_capture_dir.txt
echo "-- $SSD free: $FREE GB"
sh tools/tda2_scp.sh tda2/follow_slot.py tda2/start_followers.sh tda2/stop_followers.sh tda2:/tmp/ || exit 1

netstat -ano | grep -qE ":$(C studio.port) .*LISTEN" || { echo "!! mmWave Studio's Lua server is not listening (open Studio, wait for 'Matlab Engine Started!')"; exit 4; }
sh tools/studio_cmd.sh start > /dev/null || exit 4
studio "dofile(\"$WD/lua/harness.lua\")" || exit 4
studio "set_mirror_log(\"$WD/$STUDIO_LOG\")" || exit 4
echo "-- Studio: reconfiguring the radar (profile, chirps, frame) ..."
studio "run_logged(\"$RECONF\")" 300 || exit 4
studio_check reconfig || exit 5

sh tools/tda2_ssh.sh "sh /tmp/stop_followers.sh > /dev/null; rm -f /tmp/follow_*.log; [ -e $SSD/$DIR ] && echo EXISTS" | grep -q EXISTS && { echo "!! $SSD/$DIR already exists on the board"; exit 9; }
sh tools/tda2_ssh.sh "BASE=$SSD FB=$FB NICE=$NICE POLL=$POLL PORTS='$PORTS' sh /tmp/start_followers.sh $DIR $PC_IP" > "$RUN/followers.txt" 2>&1 &
FPID=$!
sleep 1
if [ -f "$STOP" ]; then echo ">>> stop requested before ARM: not starting the capture"; board_stop; rm -f "$LOCK" "$STOP"; exit 0; fi
echo ">>> Studio: ARM + Start Frame ..."
studio "run_logged(\"$START\")" 120 || exit 4
studio_check start || { board_stop; exit 5; }
echo ">>> STREAMING ($DIR). Stop: sh tools/stop_stream.sh (or after ${DUR} s if DUR > 0)"
echo "$DIR" > "$LOCK"
n=0
while [ ! -f "$STOP" ]; do sleep 1; n=$((n + 1)); [ "$DUR" -gt 0 ] && [ $n -ge "$DUR" ] && break; done
echo ">>> stopping: Cascade_StopCapture.lua ($(date +%H:%M:%S))"
studio "run_logged(\"$STOPLUA\")" 60
studio_check stop
rm -f "$LOCK" "$STOP"
sleep 2
board_stop
wait $FPID 2>/dev/null
for d in master slave1 slave2 slave3; do
  sh tools/tda2_scp.sh "tda2:/tmp/follow_$d.log" "$RUN/" 2>/dev/null
  sh tools/tda2_scp.sh "tda2:$SSD/$DIR/${d}_*_idx.bin" "$RUN/" 2>/dev/null
done
sh tools/tda2_ssh.sh "ls -l $SSD/$DIR/; df -h $SSD" > "$RUN/ssd_listing.txt" 2>&1
python tools/capture_stats.py "$DIR" "$IFI" | tee "$RUN/stats.txt"
echo "== done: $RUN/ (capture on the SSD: $SSD/$DIR)"
