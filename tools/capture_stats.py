"""Prints frames captured, frames lost on the TDA and the longest gap per device from the idx files of a run (logs/runs/<dir>/)."""
import glob
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cfg  # noqa: E402
from parse_idx import parse_idx  # noqa: E402
from tcp_tail_listener import DEVICES  # noqa: E402


def device_timestamps(run_dir, dev):
    ts = []
    for f in sorted(glob.glob(os.path.join(run_dir, "%s_*_idx.bin" % dev))):
        _, recs = parse_idx(f)
        ts.append(recs["timestamp_us"].astype(np.int64) / 1e6)
    return np.concatenate(ts) if ts else np.zeros(0)


def stats(ts, period_s):
    if len(ts) < 2:
        return dict(frames=len(ts), expected=len(ts), lost=0, longest_ms=0.0, stalls=0)
    g = np.diff(ts)
    expected = int(round((ts[-1] - ts[0]) / period_s)) + 1
    return dict(frames=len(ts), expected=expected, lost=expected - len(ts), longest_ms=float(g.max() * 1e3),
                stalls=int(np.sum(g > 1.75 * period_s)))


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print("usage: python tools/capture_stats.py [RUN_DIR_OR_NAME] [PERIOD_MS]   (default: the newest run under logs/runs/)")
        return
    run_dir = sys.argv[1] if len(sys.argv) > 1 else None
    if run_dir and not os.path.isdir(run_dir):
        run_dir = os.path.join(cfg.ROOT, "logs", "runs", run_dir)
    if not run_dir:
        runs = sorted(glob.glob(os.path.join(cfg.ROOT, "logs", "runs", "*")))
        run_dir = runs[-1] if runs else None
    if not run_dir or not glob.glob(os.path.join(run_dir, "master_*_idx.bin")):
        print("no idx files in %s" % run_dir)
        return
    period = float(sys.argv[2]) / 1e3 if len(sys.argv) > 2 else cfg.get("capture.period_ms") / 1e3
    print("run %s (period %.0f ms)" % (os.path.basename(run_dir), period * 1e3))
    print("  %-7s %8s %8s %6s %8s %10s" % ("device", "captured", "expected", "lost", "stalls", "longest ms"))
    for d in DEVICES:
        s = stats(device_timestamps(run_dir, d), period)
        print("  %-7s %8d %8d %6d %8d %10.0f" % (d, s["frames"], s["expected"], s["lost"], s["stalls"], s["longest_ms"]))


if __name__ == "__main__":
    main()
