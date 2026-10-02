"""Synthetic point target at 5 m with known per-channel phase and per-TX delay offsets: generate() recovers them and apply_to_cube() removes them."""
import os
import sys
import tempfile

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from cascade_dsp.calibration import CalibrationMatrix  # noqa: E402
from cascade_dsp.geometry import TX_TO_ENABLE  # noqa: E402

FS, SLOPE, N, LOOPS = 8e6, 78.986e12, 256, 4
C = 3e8


def synth(range_m=5.0, rx_phase_deg=None, tx_delay_bins=None, seed=0):
    rng = np.random.default_rng(seed)
    n = np.arange(N)
    f_beat = 2 * range_m * SLOPE / C
    cube = np.zeros((16, N, 12, LOOPS), dtype=np.complex64)
    for c in range(12):
        t = TX_TO_ENABLE[c] - 1
        for r in range(16):
            ph = np.radians(rx_phase_deg[t, r]) if rx_phase_deg is not None else 0.0
            df = (tx_delay_bins[t] if tx_delay_bins is not None else 0.0) * FS / N
            sig = 1000 * np.exp(1j * (2 * np.pi * (f_beat + df) * n / FS + ph))
            for l in range(LOOPS):
                cube[r, :, c, l] = sig + 2 * (rng.standard_normal(N) + 1j * rng.standard_normal(N))
    return cube


def test_generate_and_apply():
    rng = np.random.default_rng(1)
    rx_phase = rng.uniform(-150, 150, size=(12, 16))
    tx_delay = np.array([0.0, 0.4, -0.6, 0.2, 0.0, 0.8, -0.2, 0.5, 0.3, -0.4, 0.6, 0.1])
    cube = synth(5.0, rx_phase, tx_delay)
    cal = CalibrationMatrix.generate(cube, target_range_m=5.0, fs=FS, slope=SLOPE, interp=5, source="synthetic")
    assert cal.RangeMat.shape == (12, 16)
    est = cal.estimated_target_range(C / (2 * SLOPE * N / FS))
    assert abs(est - 5.0) < 0.15, est
    ref = TX_TO_ENABLE[0] - 1
    inj = np.angle(np.exp(1j * np.radians(rx_phase - rx_phase[ref, 0])))
    got = np.angle(np.exp(1j * np.radians(cal.AngleMat - cal.AngleMat[ref, 0])))
    d = np.angle(np.exp(1j * (got - inj)))
    per_tx = np.array([np.angle(np.mean(np.exp(1j * d[t]))) for t in range(12)])
    resid = np.degrees(np.angle(np.exp(1j * (d - per_tx[:, None]))))
    assert np.max(np.abs(resid)) < 2.0, np.max(np.abs(resid))
    cal2 = CalibrationMatrix.generate(cal.apply_to_cube(cube, FS, SLOPE), target_range_m=5.0, fs=FS, slope=SLOPE, interp=5)
    ang = np.degrees(np.angle(np.exp(1j * np.radians(cal2.AngleMat - cal2.AngleMat[ref, 0]))))
    assert np.max(np.abs(ang)) < 1.5, np.max(np.abs(ang))
    assert np.ptp(cal2.RangeMat) <= 1, np.ptp(cal2.RangeMat)
    d = tempfile.mkdtemp()
    p = os.path.join(d, "calib.npz")
    cal.save(p)
    cal3 = CalibrationMatrix.load(p)
    np.testing.assert_array_equal(cal3.RangeMat, cal.RangeMat)
    np.testing.assert_allclose(cal3.PeakValMat, cal.PeakValMat)
    png = cal.plot(os.path.join(d, "calib.png"), fs=FS, slope=SLOPE)
    assert os.path.getsize(png) > 1000
    print("  calibration: target %.2f m, max residual after correction %.2f deg" % (est, np.max(np.abs(ang))))


def test_identity_leaves_data():
    cube = synth(5.0)
    ident = CalibrationMatrix(np.full((12, 16), 100.0), np.ones((12, 16), dtype=complex), np.zeros((12, 16)), SLOPE, FS)
    out = ident.apply_to_cube(cube, FS, SLOPE)
    np.testing.assert_allclose(out, cube, rtol=1e-6, atol=1e-3)


if __name__ == "__main__":
    test_generate_and_apply()
    test_identity_leaves_data()
    print("all calibration tests passed")
