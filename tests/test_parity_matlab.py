"""Our numpy chain vs TI's MATLAB chain on one reference frame (validation/ti_home_far_run_frame2.mat from extras/run_ti_parity.m); skipped when the .mat is absent."""
import os
import sys
import time

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from cascade_dsp.geometry import CascadeGeometry  # noqa: E402
from cascade_dsp.pipeline import Pipeline, RadarParams, read_tda_frame  # noqa: E402

MAT = os.path.join(ROOT, "validation", "ti_home_far_run_frame2.mat")
DATA = os.path.join(ROOT, "validation", "home_far_run")


def load_mat():
    import h5py
    out = {}
    with h5py.File(MAT, "r") as f:
        for k in ("adcData_tx1", "rangeFFTOut", "DopplerFFTOut", "sig_integrate", "ra_static", "mag_data_static"):
            a = np.array(f[k])
            if a.dtype.names and "real" in a.dtype.names:
                a = a["real"] + 1j * a["imag"]
            out[k] = a.T
        for k in ("frameIdx", "rangeBinSize", "velocityBinSize", "d_optimal", "centerFreq"):
            out[k] = float(np.array(f[k]).ravel()[0])
    return out


def rel_err(a, b):
    return float(np.max(np.abs(a - b)) / np.max(np.abs(b)))


def test_parity():
    if not os.path.exists(MAT) or not os.path.isdir(DATA):
        print("  (skipped: no validation/ti_home_far_run_frame2.mat + validation/home_far_run; see extras/run_ti_parity.m)")
        return
    m = load_mat()
    frame0 = int(m["frameIdx"]) - 1
    p = RadarParams(samples=256, chirps=12, loops=128)
    assert abs(p.range_bin_size - m["rangeBinSize"]) < 1e-9, (p.range_bin_size, m["rangeBinSize"])
    assert abs(p.velocity_bin_size - m["velocityBinSize"]) < 1e-9, (p.velocity_bin_size, m["velocityBinSize"])
    geo = CascadeGeometry(center_freq_ghz=p.center_freq_ghz)
    assert abs(geo.d_optimal - m["d_optimal"]) < 1e-6, (geo.d_optimal, m["d_optimal"])
    pipe = Pipeline(p, geo)
    cube = read_tda_frame(DATA, frame0, 256, 12, 128)
    t0 = time.perf_counter()
    adc = pipe.frame_to_tx_cubes(cube)
    e0 = rel_err(adc[:, :, :, 0], m["adcData_tx1"])
    assert e0 < 1e-6, "adc reorder mismatch %.3g" % e0
    rng = pipe.range_fft(adc)
    e1 = rel_err(rng, m["rangeFFTOut"])
    dop = pipe.doppler_fft(rng)
    e2 = rel_err(dop, m["DopplerFFTOut"])
    rd = pipe.rd_map(dop)
    e3 = float(np.max(np.abs(rd - m["sig_integrate"])))
    ra = pipe.ra_map(dop, db=False)
    corr = float(np.corrcoef(ra.ravel(), m["ra_static"].ravel())[0, 1])
    dt = time.perf_counter() - t0
    print("  adc rel err %.2e | range rel err %.2e | Doppler rel err %.2e | RD max abs err %.2e dB | RA corr %.6f | %.0f ms for 128 loops"
          % (e0, e1, e2, e3, corr, dt * 1e3))
    assert e1 < 1e-4, "range cube rel err %.3g" % e1
    assert e2 < 1e-3, "Doppler cube rel err %.3g" % e2
    assert e3 < 1e-3, "RD map err %.3g dB" % e3
    assert corr > 0.99, "RA map correlation %.4f" % corr
    idx = np.arange(5, 256 - 20 + 1)
    ours = ra[idx, :]
    ours_plot = np.flipud(np.concatenate([ours, ours[:, :1]], axis=1).T)
    assert m["mag_data_static"].shape == ours_plot.shape
    e5 = rel_err(ours_plot, m["mag_data_static"])
    assert e5 < 1e-4, "plotted RA rel err %.3g" % e5


if __name__ == "__main__":
    test_parity()
    print("parity test done")
