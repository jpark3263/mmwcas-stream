"""Builds calib.npz from a recording of a corner reflector on boresight at a known range (frames are stacked as chirp loops and averaged)."""
import argparse
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cfg  # noqa: E402
sys.path.insert(0, cfg.ROOT)
from live_maps import recording_frames  # noqa: E402
from cascade_dsp.calibration import CalibrationMatrix  # noqa: E402
from cascade_dsp.pipeline import RadarParams  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("recording", help="captures/<name>/ with the reflector")
    ap.add_argument("--range", type=float, required=True, help="reflector distance in m")
    ap.add_argument("--frames", type=int, default=50, help="frames to average")
    ap.add_argument("--out", default=os.path.join(cfg.ROOT, "calib.npz"))
    a = ap.parse_args()
    frames = []
    for cube in recording_frames(a.recording):
        frames.append(cube[:, :, :, 0])
        if len(frames) >= a.frames:
            break
    cube = np.stack(frames, axis=-1)
    p = RadarParams()
    cal = CalibrationMatrix.generate(cube, target_range_m=a.range, fs=p.fs, slope=p.slope, source=a.recording)
    cal.save(a.out)
    png = cal.plot(os.path.splitext(a.out)[0] + ".png", fs=p.fs, slope=p.slope)
    print("estimated reflector range %.2f m (expected %.2f); wrote %s and %s" % (cal.estimated_target_range(p.range_resolution), a.range, a.out, png))


if __name__ == "__main__":
    main()
