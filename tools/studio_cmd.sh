#!/bin/sh
# Client of the Studio bridge: `start` / `stop` the bridge daemon, or send Lua ('text' or -f file, optional timeout s); exit 0 iff every command returned RC=0.
ROOT=$(cd "$(dirname "$0")/.." && pwd) || exit 1
cd "$ROOT" || exit 1
SPOOL="${STUDIO_SPOOL:-$TEMP/mmwcas_studio_spool}"
mkdir -p "$SPOOL"
alive() { m=$(stat -c %Y "$SPOOL/bridge.alive" 2>/dev/null) || return 1; [ $(( $(date +%s) - m )) -le 5 ]; }
case "$1" in
  start)
    if alive; then echo "bridge already alive (pid $(cat "$SPOOL/bridge.pid" 2>/dev/null))"; exit 0; fi
    DLL="$(python tools/cfg.py studio.dir)/mmWaveStudio/Clients/RtttNetClientController/RtttNetClientAPI.dll"
    PORT=$(python tools/cfg.py studio.port); HOST=$(python tools/cfg.py studio.host)
    [ -f "$DLL" ] || { echo "bridge: $DLL not found (config.toml studio.dir)"; exit 3; }
    rm -f "$SPOOL/bridge.stop" "$SPOOL/bridge.alive"
    powershell.exe -NoProfile -Command "Start-Process powershell.exe -WindowStyle Hidden -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','$(cygpath -w "$ROOT/tools/studio_bridge.ps1")','-Spool','$(cygpath -w "$SPOOL")','-Dll','$(cygpath -w "$DLL")','-Ip','$HOST','-Port','$PORT' -RedirectStandardOutput '$(cygpath -w "$SPOOL/bridge.console.txt")' -RedirectStandardError '$(cygpath -w "$SPOOL/bridge.console.err.txt")'" >/dev/null 2>&1
    for i in $(seq 1 30); do alive && { echo "bridge started (pid $(cat "$SPOOL/bridge.pid"))"; exit 0; }; sleep 0.5; done
    echo "bridge failed to start:"; tail -3 "$SPOOL/bridge.log" 2>/dev/null; exit 3 ;;
  stop)
    touch "$SPOOL/bridge.stop"; for i in $(seq 1 20); do alive || { echo "bridge stopped"; exit 0; }; sleep 0.5; done; echo "bridge did not stop"; exit 1 ;;
esac
alive || { echo "bridge not running (sh tools/studio_cmd.sh start)"; exit 3; }
if [ "$1" = "-f" ]; then SRC=$2; TO=${3:-120}; else SRC=""; LUA=$1; TO=${2:-120}; fi
NAME="req_$(date +%s%N)_$$"
if [ -n "$SRC" ]; then cp "$SRC" "$SPOOL/$NAME.tmp"; else printf '%s\n' "$LUA" > "$SPOOL/$NAME.tmp"; fi
mv "$SPOOL/$NAME.tmp" "$SPOOL/$NAME.lua"
n=0
while [ ! -f "$SPOOL/$NAME.rc" ]; do
  sleep 0.25; n=$((n + 1))
  [ $n -ge $((TO * 4)) ] && { echo "TIMEOUT waiting for reply ($TO s); the command may still be running in Studio"; exit 124; }
done
cat "$SPOOL/$NAME.rc"; echo
grep -q "^RC=" "$SPOOL/$NAME.rc" && ! grep -qE "^RC=[1-9]" "$SPOOL/$NAME.rc"
RC=$?
rm -f "$SPOOL/$NAME.rc"
exit $RC
