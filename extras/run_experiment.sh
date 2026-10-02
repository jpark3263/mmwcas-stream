#!/bin/sh
# Diagnostic capture: like tools/run_capture.sh plus board monitors (growth, top, interrupts, nERROR), clock offsets, a timed headless listener and the latency analysis.
#   sh extras/run_experiment.sh <DURATION_S> [NAME]
#   env: LOOPS, PERIOD_MS (config.toml defaults); FOLLOWER=slot|none; LISTENER=1|0; QUIET=1 (no growth/top/irq monitors); NFILES=1|0 (preallocate); NFRAMES=0 (TDA frame limit)
ROOT=$(cd "$(dirname "$0")/.." && pwd) || exit 1
cd "$ROOT" || exit 1
WD=$(pwd -W 2>/dev/null || pwd)
C() { python tools/cfg.py "$1"; }
TDA_IP=$(C tda.ip); PC_IP=$(C pc.ip); PORTS=$(C pc.ports); SSD=$(C tda.ssd); MINFREE=$(C tda.free_gb_min)
NICE=$(C follower.nice); POLL=$(C follower.poll_s); SAMPLES=$(C capture.samples); CHIRPS=$(C capture.chirps)
LOOPS=${LOOPS:-$(C capture.loops)}; IFI=${PERIOD_MS:-$(C capture.period_ms)}; DUR=${1:?usage: run_experiment.sh DURATION_S [NAME]}; NAME=$2
FOLLOWER=${FOLLOWER:-slot}; LISTENER=${LISTENER:-1}; NFILES=${NFILES:-1}; NFRAMES=${NFRAMES:-0}
TS=$(date +%Y%m%d_%H%M%S); DIR="mmwcas_${NAME:+${NAME}_}$TS"
FB=$((SAMPLES * CHIRPS * LOOPS * 16))
RUN=logs/runs/$DIR; STUDIO_LOG=logs/stream_studio.txt
mkdir -p "$RUN" lua/generated
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
board_stop() { sh tools/tda2_ssh.sh "sh /tmp/stop_followers.sh; busybox pkill -f irq_monitor.sh; busybox pkill -f growth_monitor.py; busybox pkill -f nerror_gpio.py; busybox pkill -f 'top -b -d 1'" >> "$RUN/followers.txt" 2>&1; }

echo "== experiment $DIR: ${IFI} ms x ${LOOPS} loop(s), frame_bytes/device=$FB, ${DUR}s, follower=$FOLLOWER listener=$LISTENER nfiles=$NFILES nframes=$NFRAMES  ($(date))" | tee "$RUN/clock.txt"
python tools/make_config.py --loops "$LOOPS" --period-ms "$IFI" --capture-dir "$DIR" --tag "$DIR" > /dev/null || exit 2
RECONF="$WD/lua/generated/Cascade_Reconfig_$DIR.lua"; START="$WD/lua/generated/Cascade_StartCapture_$DIR.lua"; STOPLUA="$WD/lua/Cascade_StopCapture.lua"
sed -i "s/^n_files_allocation .*/n_files_allocation              =   $NFILES/; s/^num_frames_to_capture .*/num_frames_to_capture           =   $NFRAMES/" "lua/generated/Cascade_StartCapture_$DIR.lua"
FREE=$(python tools/ssd_cleanup.py --free 2>/dev/null); FREE=${FREE%.*}
if [ -z "$FREE" ] || [ "$FREE" -lt "$MINFREE" ]; then echo "!! $SSD has ${FREE:-?} GB free (< $MINFREE GB): refusing to start"; exit 7; fi
PREV=$(cat logs/last_capture_dir.txt 2>/dev/null)
[ -n "$PREV" ] && [ "$PREV" != "$DIR" ] && { echo "-- previous run $PREV:"; python tools/ssd_cleanup.py --dir "$PREV" 2>&1 | grep -E "^(DELETED|keep)"; }
echo "$DIR" > logs/last_capture_dir.txt
sh tools/tda2_scp.sh tda2/follow_slot.py tda2/start_followers.sh tda2/stop_followers.sh extras/tda2/time_server.py extras/tda2/growth_monitor.py extras/tda2/irq_monitor.sh extras/tda2/nerror_gpio.py tda2:/tmp/ || exit 1
sh tools/tda2_ssh.sh "python /tmp/nerror_gpio.py 0.25 $((DUR + 100))" > "$RUN/gpio.txt" 2>&1 &
NPID=$!

sh tools/studio_cmd.sh start > /dev/null || exit 4
studio "dofile(\"$WD/lua/harness.lua\")" || exit 4
studio "set_mirror_log(\"$WD/$STUDIO_LOG\")" || exit 4
echo "-- Studio: reconfiguring the radar ..."
studio "run_logged(\"$RECONF\")" 300 || exit 4
studio_check reconfig || exit 5

sh tools/tda2_ssh.sh 'netstat -tln | grep -q ":5010 " || (nohup python /tmp/time_server.py 5010 >/dev/null 2>&1 &); sh /tmp/stop_followers.sh >/dev/null; rm -f /tmp/follow_*.log; echo board ready'
sh tools/tda2_ssh.sh "[ -e $SSD/$DIR ] && echo EXISTS" | grep -q EXISTS && { echo "!! $SSD/$DIR already exists on the board"; exit 9; }
python extras/clock_offset.py --label before | tee -a "$RUN/clock.txt"
python extras/vsdk_timer_offset.py --label before | tee -a "$RUN/clock.txt"

if [ "$LISTENER" = 1 ]; then
  python extras/timed_listener.py "$RUN" --loops "$LOOPS" --duration $((DUR + 15)) > "$RUN/listener_console.txt" 2>&1 &
else
  sleep $((DUR + 15)) &
fi
LPID=$!
sleep 2
if [ "$FOLLOWER" = slot ]; then
  sh tools/tda2_ssh.sh "BASE=$SSD FB=$FB NICE=$NICE POLL=$POLL PORTS='$PORTS' sh /tmp/start_followers.sh $DIR $PC_IP" > "$RUN/followers.txt" 2>&1 &
else
  echo "no board followers (FOLLOWER=$FOLLOWER)" > "$RUN/followers.txt"; sleep 1 &
fi
SPID=$!
sh tools/tda2_ssh.sh "sh /tmp/irq_monitor.sh $((DUR + 10)) 0.25" > "$RUN/irq.txt" 2>&1 &
IPID=$!
GPID=""; TPID=""
if [ "${QUIET:-0}" != 1 ]; then
  sh tools/tda2_ssh.sh "python /tmp/growth_monitor.py $SSD/$DIR 0.02 $((DUR + 10))" > "$RUN/growth.txt" 2>&1 &
  GPID=$!
  sh tools/tda2_ssh.sh "top -b -d 1 -n $((DUR + 10)) | awk '/^Mem:/{getline u < \"/proc/uptime\"; close(\"/proc/uptime\"); sub(/ .*/, \"\", u); print \"### \" u} {print}'" > "$RUN/top.txt" 2>&1 &
  TPID=$!
fi
sleep 1
echo ">>> Studio: ARM + Start Frame ..."
studio "run_logged(\"$START\")" 120 || exit 4
studio_check start || { board_stop; exit 5; }
echo ">>> capturing for ${DUR} s ..."
sleep "$DUR"
echo ">>> stopping ($(date +%H:%M:%S))"
studio "run_logged(\"$STOPLUA\")" 60
studio_check stop
kill $LPID 2>/dev/null; wait $LPID 2>/dev/null
sleep 2
board_stop
wait $SPID $GPID $TPID $IPID $NPID 2>/dev/null
python extras/clock_offset.py --label after | tee -a "$RUN/clock.txt"
python extras/vsdk_timer_offset.py --label after | tee -a "$RUN/clock.txt"
for d in master slave1 slave2 slave3; do
  sh tools/tda2_scp.sh "tda2:/tmp/follow_$d.log" "$RUN/" 2>/dev/null
  sh tools/tda2_scp.sh "tda2:$SSD/$DIR/${d}_*_idx.bin" "$RUN/" 2>/dev/null
done
sh tools/tda2_ssh.sh "ls -l $SSD/$DIR/; df -h $SSD" > "$RUN/ssd_listing.txt" 2>&1
python tools/capture_stats.py "$DIR" "$IFI" | tee "$RUN/stats.txt"
python extras/analyze_run.py "$RUN" --loops "$LOOPS" --period-ms "$IFI" | tee "$RUN/analysis.txt"
python extras/irq_delta.py "$RUN" | tee -a "$RUN/analysis.txt"
python extras/run_summary.py "$RUN"
echo "== done: $RUN/"
