"""Times cascade_dsp.pipeline per stage: python extras/bench_pipeline.py [--loops 1] [--iters 200] [--from-capture <dir with <dev>_0000_data.bin>]"""
import argparse
import os
import sys

import numpy as np

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
from cascade_dsp.pipeline import Pipeline, RadarParams, read_tda_frame  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--loops", type=int, default=1)
    ap.add_argument("--iters", type=int, default=200)
    ap.add_argument("--from-capture", default=os.path.join(ROOT, "validation", "home_far_run"), help="128-loop capture directory for real data")
    a = ap.parse_args()
    p = RadarParams(samples=256, chirps=12, loops=a.loops)
    pipe = Pipeline(p)
    if os.path.isdir(a.from_capture) and a.loops <= 128:
        cube = np.ascontiguousarray(read_tda_frame(a.from_capture, 1, 256, 12, 128)[:, :, :, :a.loops])
    else:
        rng = np.random.default_rng(0)
        cube = (rng.standard_normal((16, 256, 12, a.loops)) + 1j * rng.standard_normal((16, 256, 12, a.loops))).astype(np.complex64)
    pipe.process(cube)
    stages = {}
    tot = []
    for _ in range(a.iters):
        r = pipe.process(cube)
        for k, v in r["timing_ms"].items():
            stages.setdefault(k, []).append(v)
        tot.append(r["timing_ms"]["total"])
    print("pipeline timing, loops=%d, %d iterations (ms):" % (a.loops, a.iters))
    for k, v in stages.items():
        print("  %-12s median %7.2f   p90 %7.2f   max %7.2f" % (k, np.median(v), np.percentile(v, 90), np.max(v)))
    budget = 10.0
    print("  budget %.0f ms per frame: %s (median total %.2f ms, p90 %.2f ms)" % (budget, "OK" if np.percentile(tot, 90) < budget else "TOO SLOW", np.median(tot), np.percentile(tot, 90)))


if __name__ == "__main__":
    main()
