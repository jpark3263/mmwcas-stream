#!/bin/bash
# Runs on the TDA2 (read-only): prints /proc/interrupts every INTERVAL s for DURATION s, each snapshot prefixed "### <uptime>". Usage: /tmp/irq_monitor.sh DURATION_S [INTERVAL_S=0.25]
DUR=${1:-60}; INT=${2:-0.25}
END=$(( $(cut -d. -f1 /proc/uptime) + DUR ))
while [ $(cut -d. -f1 /proc/uptime) -lt $END ]; do
  echo "### $(cut -d' ' -f1 /proc/uptime)"
  cat /proc/interrupts
  sleep $INT
done
echo "### end"
