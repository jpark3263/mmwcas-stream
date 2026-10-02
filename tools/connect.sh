#!/bin/sh
# Once per boot: ConnectTDA, SOP reset, power-on, firmware download and the base configuration of the four AWR2243s through mmWave Studio. Stops on any "Failed" line.
#   sh tools/connect.sh      env: LOOPS, PERIOD_MS (defaults from config.toml), DRY=1 (print the plan only)
ROOT=$(cd "$(dirname "$0")/.." && pwd) || exit 1
cd "$ROOT" || exit 1
WD=$(pwd -W 2>/dev/null || pwd)
C() { python tools/cfg.py "$1"; }
LOOPS=${LOOPS:-$(C capture.loops)}; IFI=${PERIOD_MS:-$(C capture.period_ms)}
mkdir -p logs lua/generated
python tools/make_config.py --loops "$LOOPS" --period-ms "$IFI" > /dev/null || exit 2
CFG="$WD/lua/generated/Cascade_Configuration_MIMO.lua"
if [ "${DRY:-0}" = 1 ]; then
  echo "DRY=1: would check the board at $(C tda.ip) over ssh, start the Studio bridge on port $(C studio.port), run $WD/lua/Cascade_StopCapture.lua (pre-flight) and $CFG, then check logs/connect_studio.txt for 'Failed'"
  exit 0
fi
echo "-- board:"; sh tools/tda2_ssh.sh "cut -d' ' -f1 /proc/uptime; ps | grep -v grep | grep -c apps.out; netstat -tn | grep -c ':5001 .*ESTABLISHED'" | tr '\n' ' '; echo "(uptime s, apps.out count (1), established sessions on 5001 (0 before the first connect))"
netstat -ano | grep -qE ":$(C studio.port) .*LISTEN" || { echo "!! Studio's Lua server is not listening (open Studio, wait for 'Matlab Engine Started!')"; exit 4; }
sh tools/studio_cmd.sh stop > /dev/null 2>&1; sh tools/studio_cmd.sh start || exit 4
sh tools/studio_cmd.sh "dofile(\"$WD/lua/harness.lua\")" > /dev/null || exit 4
sh tools/studio_cmd.sh "set_mirror_log(\"$WD/logs/connect_studio.txt\")" > /dev/null
sh tools/studio_cmd.sh "run_logged(\"$WD/lua/Cascade_StopCapture.lua\")" 60 > /dev/null 2>&1
echo "-- Studio: full configuration (ConnectTDA, SOP, power-on, FW, profile/chirp/frame) ... ~35 s"
sh tools/studio_cmd.sh "run_logged(\"$CFG\")" 300 | head -1
n=0; while [ $n -lt 300 ] && ! grep -q "### run_logged END .*Cascade_Configuration_MIMO.lua" logs/connect_studio.txt 2>/dev/null; do sleep 2; n=$((n + 2)); done
awk '/### run_logged BEGIN/{buf=""} {buf=buf $0 "\n"} END{printf "%s", buf}' logs/connect_studio.txt > logs/connect_last.txt
if grep -qiE "Failed|ok=false" logs/connect_last.txt; then echo "!! FAILED:"; grep -iE "Failed|ok=false" logs/connect_last.txt | head -3; echo "   -> USAGE.md: power-cycle the board with Studio open"; exit 5; fi
sh tools/studio_cmd.sh 'local ok, st = pcall(ar1.TDACaptureCard_StopRecord_mult, 1); WriteToLog("connect.sh StopRecord pre-flight -> ok="..tostring(ok).." status="..tostring(st).."\n", "blue")' 30 | head -1 | sed 's/^/-- /'
echo "-- connected and configured: $(grep -c uccessful logs/connect_last.txt) success lines. Next: sh tools/stream.sh"
