"""One summary line for a run directory: were the capture files created and filled, idx frame count and period, SSD flush step (from growth.txt)."""
import glob
import os
import sys

import numpy as np

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from parse_idx import parse_idx  # noqa: E402

run = sys.argv[1]
if not os.path.isdir(run):
    run = os.path.join(ROOT, "logs", "runs", run)
files = flush = "-"
g = os.path.join(run, "growth.txt")
if os.path.exists(g):
    rows = [l.split() for l in open(g) if not l.startswith("#")]
    m = [(float(r[1]), int(r[3])) for r in rows if len(r) == 4 and r[2] == "master_0000_data.bin"]
    sizes = [s for _, s in m]; created = [t for t, s in m if s == 0]; final = max(sizes) if sizes else -1
    gone_after = [t for t, s in m if s == -1 and created and t > created[0]]
    files = "YES (final %.1f MB)" % (final / 1e6) if final > 0 else ("NO (0 B at %.2f s, gone at %.2f s)" % (created[0], gone_after[0]) if created and gone_after else "NO (never created)")
    steps = np.diff([s for s in sizes if s > 0]); steps = steps[steps > 0]
    flush = "-" if not len(steps) else "median %d B (min %d, max %d, n=%d)" % (int(np.median(steps)), steps.min(), steps.max(), len(steps))
per = "-"
idx_files = sorted(glob.glob(os.path.join(run, "master_*_idx.bin")))
if idx_files:
    ts = np.concatenate([parse_idx(f)[1]["timestamp_us"].astype(np.int64) for f in idx_files]).astype(float)
    dt = np.diff(ts) / 1e3
    per = "%d frames, dt median %.3f ms (min %.3f max %.3f)" % (len(ts), np.median(dt), dt.min(), dt.max()) if len(dt) else "%d frame" % len(ts)
print("%s | files %s | idx %s | flush step %s" % (os.path.basename(run), files, per, flush))
