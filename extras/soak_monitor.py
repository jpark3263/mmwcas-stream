"""While a stream runs: one row per interval with PC frame counts, arrival gaps, viewer stats, PC and board resources and follower progress; stops when the stream lock disappears."""
import argparse
import glob
import os
import re
import subprocess
import sys
import time

import numpy as np
import psutil

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import cfg  # noqa: E402

SSH = ["sh", os.path.join(ROOT, "tools", "tda2_ssh.sh")]
LOGS = os.path.join(ROOT, "logs")


def ssh(cmd, timeout=20):
    try:
        return subprocess.run(SSH + [cmd], capture_output=True, text=True, timeout=timeout).stdout
    except Exception as e:
        return "ssh-error %s" % e


def newest(pattern):
    f = glob.glob(pattern)
    return max(f, key=os.path.getmtime) if f else None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--interval", type=float, default=60)
    ap.add_argument("--period-ms", type=float, default=cfg.get("capture.period_ms"))
    a = ap.parse_args()
    period = a.period_ms / 1e3
    ssd = cfg.get("tda.ssd")
    lock = os.path.join(LOGS, "stream.running")
    arrival = os.path.join(LOGS, "arrivals.csv")
    out_path = os.path.join(LOGS, "soak_monitor_%s.csv" % time.strftime("%Y%m%d_%H%M%S"))
    out = open(out_path, "w", buffering=1)
    hdr = ("t_min,pc_frames,total_frames,stalls,lost_est,longest_gap_ms,mux_drops,pipeline_ms,pc_cpu_pct,pc_ram_pct,viewer_rss_mb,"
           "board_avail_mb,ssd_free_gb,follower_last_slot,follower_lag_frames,rollovers,viewer_alive")
    out.write(hdr + "\n"); print(hdr, flush=True)
    last_t = None; total = 0; pos = 0
    while os.path.exists(lock) and not (os.path.exists(arrival) and os.path.getsize(arrival) > 20):
        time.sleep(1)
    if not os.path.exists(lock):
        print("stream ended before any frame arrived", flush=True); return
    t0 = time.time()
    while True:
        time.sleep(a.interval)
        alive = os.path.exists(lock)
        gaps = []; n = 0
        with open(arrival) as f:
            f.seek(pos)
            for line in f:
                p = line.strip().split(",")
                if len(p) != 2 or not p[1][0].isdigit():
                    continue
                t = float(p[1]); n += 1
                if last_t is not None:
                    gaps.append(t - last_t)
                last_t = t
            pos = f.tell()
        total += n
        gaps = np.array(gaps) if gaps else np.zeros(0)
        stall = gaps[gaps > 1.75 * period] if len(gaps) else gaps
        lost = int(np.sum(np.round(stall / period) - 1)) if len(stall) else 0
        longest = float(gaps.max() * 1e3) if len(gaps) else 0.0
        vc = newest(os.path.join(LOGS, "viewer_*.txt"))
        drops = pipe_ms = -1
        if vc:
            last = [l for l in open(vc, errors="replace").read().splitlines() if "[live_maps] idx=" in l]
            if last:
                m = re.search(r"'incomplete_dropped': (\d+).*pipeline=([\d.]+) ms", last[-1])
                if m:
                    drops, pipe_ms = int(m.group(1)), float(m.group(2))
        cpu = psutil.cpu_percent(interval=1.0); ram = psutil.virtual_memory().percent
        rss = 0.0
        for pr in psutil.process_iter(["name", "cmdline", "memory_info"]):
            try:
                if pr.info["cmdline"] and any("live_maps.py" in c for c in pr.info["cmdline"]):
                    rss = pr.info["memory_info"].rss / 1e6
            except Exception:
                pass
        b = ssh("awk '/MemAvailable/{print $2}' /proc/meminfo; df -k %s | tail -1 | awk '{print $4}'; tail -1 /tmp/follow_master.log 2>/dev/null; grep -c ROLLOVER /tmp/follow_master.log 2>/dev/null" % ssd)
        bl = b.strip().splitlines()
        board_free = int(bl[0]) / 1024 if len(bl) > 0 and bl[0].isdigit() else -1
        ssd_free = int(bl[1]) / 1e6 if len(bl) > 1 and bl[1].isdigit() else -1
        last_slot = -1
        if len(bl) > 2:
            p = bl[2].split()
            if len(p) >= 4 and p[0][0].isdigit():
                last_slot = int(p[3])
        roll = int(bl[3]) if len(bl) > 3 and bl[3].strip().isdigit() else 0
        lag = (last_slot + 1 - total) if last_slot >= 0 else -1
        row = "%.1f,%d,%d,%d,%d,%.0f,%d,%.1f,%.0f,%.0f,%.0f,%.0f,%.1f,%d,%d,%d,%s" % (
            (time.time() - t0) / 60, n, total, len(stall), lost, longest, drops, pipe_ms, cpu, ram, rss, board_free, ssd_free, last_slot, lag, roll, alive)
        out.write(row + "\n"); print(row, flush=True)
        if not alive:
            break
    out.close()
    print("soak monitor done: %s" % out_path, flush=True)


if __name__ == "__main__":
    main()
