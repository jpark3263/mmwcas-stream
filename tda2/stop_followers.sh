#!/bin/bash
# Runs on the TDA2: kills the followers started by start_followers.sh.
for pid in $(ps | grep -E "follow_slot.py|start_followers" | grep -v grep | awk '{print $1}'); do kill $pid 2>/dev/null; done
sleep 0.2
ps | grep -E "follow_slot.py|start_followers" | grep -v grep || echo "stop_followers: nothing left running"
