#!/bin/sh
# Read-only intake of a TDA2 capture board (ssh host key, SD image, SSD, software) compared with the reference board; nothing is written on the board.
#   sh extras/board_intake.sh [LABEL]   -> logs/board_intake_<LABEL>_<ts>.txt; exit 0 = matches, 1 = attention needed, 2 = unreachable
LABEL=${1:-B}
ROOT=$(cd "$(dirname "$0")/.." && pwd) || exit 1; cd "$ROOT" || exit 1
IP=$(python tools/cfg.py tda.ip); SSDMNT=$(python tools/cfg.py tda.ssd)
mkdir -p logs
OUT="logs/board_intake_${LABEL}_$(date +%Y%m%d_%H%M%S).txt"
SSH="sh tools/tda2_ssh.sh"
REF_VSDK="REL_VISION_SDK_03_07_01_00"; REF_KERNEL="4.4.84-00041-g84382ab"; REF_PY="Python 2.7"
say() { echo "$*" | tee -a "$OUT"; }
say "== board intake ($LABEL) $(date '+%Y-%m-%d %H:%M:%S'), read-only"
if ! ping -n 1 -w 1500 "$IP" >/dev/null 2>&1; then say "!! $IP does not answer ping (no link, board off or still booting)"; exit 2; fi
KEY=$(ssh-keyscan -T 5 -t rsa "$IP" 2>/dev/null | grep -v '^#')
FP=$(printf '%s\n' "$KEY" | ssh-keygen -lf /dev/stdin 2>/dev/null)
say "   ssh host key (rsa): ${FP:-n/a}"
printf '%s\n' "$KEY" | sed "s/^$IP/tda2-board$LABEL/" >> logs/known_hosts_tda2 2>/dev/null && say "   key appended to logs/known_hosts_tda2 under the alias tda2-board$LABEL"
R=$($SSH "echo OK; cat /proc/uptime" 2>&1); case "$R" in OK*) say "   ssh OK, uptime $(echo "$R" | tail -1 | cut -d' ' -f1) s" ;; *) say "!! ssh failed: $R"; exit 2 ;; esac
say "-- SD image"
$SSH "uname -r; cat /sys/class/net/eth0/address; cat /etc/version 2>/dev/null; sed -n 1,2p /etc/os-release 2>/dev/null; \
  (strings /opt/vision_sdk/apps.out 2>/dev/null; cat /opt/vision_sdk/*.txt 2>/dev/null) | grep -oE 'REL_VISION_SDK_[0-9_]+' | sort -u | head -2; \
  ls /opt/vision_sdk 2>/dev/null | tr '\n' ' '; echo; systemctl is-active vsdk 2>/dev/null" 2>&1 | tee -a "$OUT" | sed 's/^/   /'
KERNEL=$($SSH "uname -r" 2>/dev/null); VSDK=$($SSH "strings /opt/vision_sdk/apps.out 2>/dev/null | grep -oE 'REL_VISION_SDK_[0-9_]+' | head -1" 2>/dev/null)
say "-- SSD (nothing written)"
$SSH "ls /dev/nvme* /dev/sd? 2>/dev/null | tr '\n' ' '; echo; blkid 2>/dev/null | grep -E 'nvme|/dev/sd'; mount | grep -E 'nvme|/dev/sd| $SSDMNT'; \
  df -h $SSDMNT 2>&1 | tail -1; echo CONTENT:; ls -la $SSDMNT 2>&1 | tail -n +2; du -sm $SSDMNT/* 2>/dev/null | sort -rn | head -20" 2>&1 | tee -a "$OUT" | sed 's/^/   /'
SSD_DEV=$($SSH "ls /dev/nvme0n1p1 /dev/nvme0n1 2>/dev/null | head -1"); SSD_MNT=$($SSH "mount | grep -c ' $SSDMNT '")
say "-- software"
$SSH "ps | grep -v grep | grep -E 'apps.out|follow' ; python -V 2>&1; busybox 2>&1 | head -1; which nc python; echo" 2>&1 | tee -a "$OUT" | sed 's/^/   /'
APPS=$($SSH "ps | grep -v grep | grep -c apps.out"); PY=$($SSH "python -V 2>&1"); NC=$($SSH "which nc")
say "-- comparison with the reference board"
ok=1
[ "$KERNEL" = "$REF_KERNEL" ] && say "   kernel $KERNEL = reference" || { say "!! kernel '$KERNEL' (reference: $REF_KERNEL)"; ok=0; }
[ "$VSDK" = "$REF_VSDK" ] && say "   Vision SDK $VSDK = reference" || { say "!! Vision SDK '${VSDK:-not found}' (reference: $REF_VSDK)"; ok=0; }
if [ -z "$SSD_DEV" ]; then say "!! no NVMe device: SSD missing"; ok=0
elif [ "$SSD_MNT" != 1 ]; then say "!! NVMe present but $SSDMNT not mounted (unformatted or not in fstab)"; ok=0
else say "   SSD mounted at $SSDMNT"; fi
[ "$APPS" = 1 ] && say "   apps.out running" || { say "!! apps.out processes: $APPS (expected 1)"; ok=0; }
case "$PY" in *"$REF_PY"*) say "   $PY" ;; *) say "!! python: '$PY' (expected $REF_PY)"; ok=0 ;; esac
[ -n "$NC" ] && say "   nc present ($NC)" || { say "!! nc missing"; ok=0; }
if [ $ok = 1 ]; then say "== MATCHES the reference board: connect.sh + stream.sh 30 may follow"; else say "== MISMATCH / attention needed"; fi
say "   report saved: $OUT"
[ $ok = 1 ]
