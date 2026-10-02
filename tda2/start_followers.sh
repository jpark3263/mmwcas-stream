#!/bin/bash
# Runs on the TDA2: waits for the four capture files of $1 and starts one follow_slot.py per device towards the PC ($2).
# Usage: FB=<frame_bytes> PORTS="5001 5002 5003 5004" [BASE=/mnt/ssd] [NICE=0] [POLL=0.005] sh /tmp/start_followers.sh <capture_dir> <pc_ip>
D=${BASE:-/mnt/ssd}/$1; PC=$2; NICE=${NICE:-0}; FB=${FB:-49152}; POLL=${POLL:-0.005}; PORTS=${PORTS:-"5001 5002 5003 5004"}
[ -z "$PC" ] && { echo "usage: start_followers.sh <capture_dir> <pc_ip>"; exit 2; }
DEVS="master slave1 slave2 slave3"
echo "start_followers: waiting for data files in $D (frame_bytes=$FB, pc=$PC, nice=$NICE, poll=$POLL)"
while true; do
  ok=1
  for d in $DEVS; do [ -f "$D/${d}_0000_data.bin" ] || ok=0; done
  [ $ok = 1 ] && break
  sleep 0.05
done
echo "start_followers: files present at $(cut -d' ' -f1 /proc/uptime) s uptime"
set -- $PORTS
for d in $DEVS; do
  busybox ionice -c 3 nice -n $NICE python /tmp/follow_slot.py "$D/${d}_0000_data.bin" $PC $1 --frame-bytes $FB --poll $POLL --log /tmp/follow_$d.log &
  shift
done
wait
echo "start_followers: all followers exited"
