#!/usr/bin/python
# Runs on the TDA2 (Python 2.7): prints "<time.time()> <uptime> <file> <size>" for every size change of the capture files in DIR. Usage: python /tmp/growth_monitor.py DIR [poll_s=0.01] [max_s=0]
import os, sys, time

d = sys.argv[1]
poll = float(sys.argv[2]) if len(sys.argv) > 2 else 0.01
max_s = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
names = ["master_0000_data.bin", "slave1_0000_data.bin", "slave2_0000_data.bin", "slave3_0000_data.bin",
         "master_0000_idx.bin", "slave1_0000_idx.bin", "slave2_0000_idx.bin", "slave3_0000_idx.bin"]
last = {}
t_start = time.time()


def uptime():
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0])
    except Exception:
        return -1.0


sys.stdout.write("# growth_monitor start time=%.6f uptime=%.2f dir=%s poll=%.3f\n" % (t_start, uptime(), d, poll))
sys.stdout.flush()
while True:
    now = time.time()
    try:
        present = set(os.listdir(d))
    except OSError:
        present = set()
    for n in names:
        if n in present:
            try:
                sz = os.stat(os.path.join(d, n)).st_size
            except OSError:
                continue
        else:
            sz = -1
        if last.get(n) != sz:
            last[n] = sz
            sys.stdout.write("%.6f %.2f %s %d\n" % (now, uptime(), n, sz))
            sys.stdout.flush()
    if max_s and now - t_start > max_s:
        break
    time.sleep(poll)
