"""Latency and loss analysis of one extras/run_experiment.sh run directory (listener logs, follower logs, idx files, clock offsets, growth and top logs)."""
import argparse
import glob
import json
import os
import re
import sys

import numpy as np

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import cfg  # noqa: E402
from parse_idx import parse_idx  # noqa: E402
from tcp_tail_listener import DEVICES, frame_bytes_per_device  # noqa: E402


def read_csv3(path):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return None
    a = np.loadtxt(path, delimiter=",", ndmin=2)
    return a if len(a) else None


def read_clock(path):
    res = {}
    if not os.path.exists(path):
        return res
    for line in open(path):
        for key, tag in (("clock", "# clock_offset"), ("vsdk", "# vsdk_timer_offset")):
            if line.startswith(tag):
                lab = line.split()[2]
                kv = dict(re.findall(r"(\w+)=([-\d.]+)", line))
                res.setdefault(key, {})[lab] = {k: float(v) for k, v in kv.items()}
    return res


def pct(x, p):
    return float(np.percentile(x, p)) if len(x) else float("nan")


def device_idx(run, d):
    ts = []
    for f in sorted(glob.glob(os.path.join(run, "%s_*_idx.bin" % d))):
        _, recs = parse_idx(f)
        ts.append(recs["timestamp_us"].astype(np.int64) / 1e6)
    return np.concatenate(ts) if ts else None


def main():
    c = cfg.load()["capture"]
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_dir")
    ap.add_argument("--loops", type=int, default=c["loops"])
    ap.add_argument("--period-ms", type=float, default=c["period_ms"])
    a = ap.parse_args()
    run = a.run_dir
    fb = frame_bytes_per_device(c["samples"], c["chirps"], a.loops)
    period = a.period_ms / 1e3
    fps = 1.0 / period
    print("=== analysis %s: loops=%d period=%g ms frame_bytes/device=%d expected %.2f MB/s/device, %.1f Mbit/s total"
          % (os.path.basename(run), a.loops, a.period_ms, fb, fb * fps / 1e6, 4 * fb * fps * 8 / 1e6))
    lj = os.path.join(run, "listener.json")
    if os.path.exists(lj):
        summary = json.load(open(lj))
        print("\n-- PC receive (listener):")
        for d in DEVICES:
            s = summary["per_device"][d]
            print("  %-7s bytes=%12d frames=%6d mean_rate=%6.2f MB/s connections=%d partial_at_close=%d"
                  % (d, s["bytes"], s["frames"], s["mean_rate_MBps"], s["connections"], s["partial_at_close"]))
        print("  mux: %s" % summary["mux"])
    clk = read_clock(os.path.join(run, "clock.txt"))
    up_off = vs_off = bt_off = None
    if clk.get("clock"):
        cb = clk["clock"].get("before") or list(clk["clock"].values())[0]
        up_off, bt_off = cb["uptime_minus_pc"], cb["offset_board_minus_pc"]
        if "after" in clk["clock"] and "before" in clk["clock"]:
            drift = clk["clock"]["after"]["uptime_minus_pc"] - clk["clock"]["before"]["uptime_minus_pc"]
            print("\n-- clocks: uptime-pc offset drift over the run: %.1f ms (rtt %.2f/%.2f ms)" % (drift * 1e3, cb["rtt_ms"], clk["clock"]["after"]["rtt_ms"]))
    if clk.get("vsdk"):
        v = clk["vsdk"].get("before") or list(clk["vsdk"].values())[0]
        vs_off = v["vsdk_minus_uptime_s"]
        print("   vsdk timer - uptime = %.3f s (journal-based)" % vs_off)
    vs_bt = None
    per_dev_read = {}
    for d in DEVICES:
        fl = os.path.join(run, "follow_%s.log" % d)
        ts = device_idx(run, d)
        if os.path.exists(fl) and ts is not None:
            try:
                f = np.loadtxt(fl, comments="#", ndmin=2)
                if len(f) and len(ts):
                    ends = (np.arange(len(ts)) + 1) * fb
                    j = np.searchsorted(f[:, 1], ends)
                    ok = j < len(f)
                    t_read = f[j[ok], 0]
                    per_dev_read[d] = (ts[ok], t_read)
                    cand = float(np.max(ts[ok] - t_read))
                    vs_bt = cand if vs_bt is None else max(vs_bt, cand)
            except Exception as e:
                print("  (%s: offset estimate failed: %s)" % (d, e))
    if vs_bt is not None and up_off is not None and bt_off is not None:
        vs_off = vs_bt + (bt_off - up_off)
        print("   vsdk timer - uptime from idx/follower data = %.3f s (used below)" % vs_off)
    print("\n-- per device frame accounting / latency:")
    for d in DEVICES:
        fr = read_csv3(os.path.join(run, "frames_%s.csv" % d))
        ts = device_idx(run, d)
        line = "  %-7s" % d
        if fr is not None:
            idx = fr[:, 0].astype(int)
            missing = int(idx[-1] + 1 - len(idx)) if len(idx) else 0
            dt = np.diff(fr[:, 1])
            line += " pc_frames=%d first_idx=%d last_idx=%d missing_idx=%d  inter-arrival ms: med %.1f p99 %.1f max %.1f" % (
                len(idx), idx[0], idx[-1], missing, np.median(dt) * 1e3, pct(dt, 99) * 1e3, dt.max() * 1e3)
            drift = fr[:, 2] - (fr[0, 2] + np.arange(len(fr)) * period)
            line += "\n           drift vs %.0f fps clock: end %.1f ms, max %.1f ms" % (fps, drift[-1] * 1e3, drift.max() * 1e3)
        if ts is not None and len(ts):
            dts = np.diff(ts)
            n_drop = int(np.round(dts / period).sum() - len(dts)) if len(dts) else 0
            line += "\n           idx: %d radar frames, dt med %.2f ms, radar-dropped frames (timestamp gaps) = %d" % (
                len(ts), np.median(dts) * 1e3 if len(dts) else float("nan"), n_drop)
            if fr is not None and up_off is not None and vs_off is not None:
                n = min(len(fr), len(ts))
                lat = fr[:n, 2] - ((ts[:n] - vs_off) - up_off)
                line += "\n           e2e latency (PC recv - capture) ms: med %.0f p90 %.0f max %.0f (lower bound)" % (np.median(lat) * 1e3, pct(lat, 90) * 1e3, lat.max() * 1e3)
            if d in per_dev_read and vs_bt is not None:
                ts_ok, t_read = per_dev_read[d]
                bl = t_read - (ts_ok - vs_bt)
                line += "\n           board flush->read latency ms (rel. to fastest frame): med %.0f p90 %.0f max %.0f (n=%d)" % (np.median(bl) * 1e3, pct(bl, 90) * 1e3, bl.max() * 1e3, len(bl))
        print(line)
    mx = read_csv3(os.path.join(run, "mux.csv"))
    if mx is not None:
        idx = mx[:, 0].astype(int)
        print("\n-- mux: %d 16-RX frames, idx %d..%d, missing %d" % (len(idx), idx[0], idx[-1], idx[-1] + 1 - len(idx)))
    gp = os.path.join(run, "growth.txt")
    if os.path.exists(gp):
        rows = [l.split() for l in open(gp) if not l.startswith("#")]
        m = [(float(r[0]), int(r[3])) for r in rows if len(r) == 4 and r[2] == "master_0000_data.bin" and int(r[3]) > 0]
        if len(m) > 2:
            t = np.array([x[0] for x in m]); s = np.array([x[1] for x in m], dtype=float)
            steps = np.diff(s)
            print("\n-- SSD (master_0000_data.bin): growth %.2f MB/s (expected %.2f), %d steps, step median %.1f frames, max %.1f frames"
                  % ((s[-1] - s[0]) / (t[-1] - t[0]) / 1e6, fb * fps / 1e6, len(steps), np.median(steps) / fb, steps.max() / fb))
    tp = os.path.join(run, "top.txt")
    if os.path.exists(tp):
        txt = open(tp).read()
        idle = [float(x) for x in re.findall(r"([\d.]+)% idle", txt)]
        sysp = [float(x) for x in re.findall(r"([\d.]+)% sys", txt)]
        foll = [float(x) for x in re.findall(r"\s([\d.]+)\s+python /tmp/follow_slot.py", txt)]
        apps = [float(x) for x in re.findall(r"\s([\d.]+)\s+\./apps.out", txt)]
        jrnl = [float(x) for x in re.findall(r"\s([\d.]+)\s+/lib/systemd/systemd-journald", txt)]
        print("\n-- board CPU (%d snapshots): idle min/med %.1f/%.1f %%, sys med %.1f %%, follower per-process med %.1f %% (max %.1f), apps.out med %.1f %%, journald med %.1f %%"
              % (len(idle), min(idle) if idle else -1, np.median(idle) if idle else -1, np.median(sysp) if sysp else -1,
                 np.median(foll) if foll else -1, max(foll) if foll else -1, np.median(apps) if apps else -1, np.median(jrnl) if jrnl else -1))


if __name__ == "__main__":
    main()
