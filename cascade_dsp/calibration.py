"""Per-virtual-channel calibration (generate from a corner-reflector frame, apply to the mux cube), ported from TI's calibrationCascade and genCalibrationMatrixCascade (THIRD_PARTY.md)."""
import numpy as np

from .geometry import TX_TO_ENABLE
from .pipeline import SPEED_OF_LIGHT_TI, matlab_hanning


def average_phase(ph_rad):
    ph = np.asarray(ph_rad, dtype=float)
    diff = np.angle(np.exp(1j * (ph - ph[0])))
    return float(np.mean(ph[0] + diff))


def matlab_round(x):
    return np.floor(np.asarray(x) + 0.5)


class CalibrationMatrix:
    def __init__(self, range_mat, peak_val_mat, angle_mat, slope_calib, fs_calib, interp=5, samples=256,
                 tx_to_enable=TX_TO_ENABLE, rx_mismatch=None, tx_mismatch=None, source="", target_range_m=None):
        self.RangeMat = np.asarray(range_mat, dtype=float)
        self.PeakValMat = np.asarray(peak_val_mat, dtype=complex)
        self.AngleMat = np.asarray(angle_mat, dtype=float)
        self.slope_calib = float(slope_calib)
        self.fs_calib = float(fs_calib)
        self.interp = int(interp)
        self.samples = int(samples)
        self.tx_to_enable = np.asarray(tx_to_enable, dtype=int)
        self.RxMismatch = rx_mismatch
        self.TxMismatch = tx_mismatch
        self.source = source
        self.target_range_m = target_range_m

    def save(self, path):
        np.savez(path, RangeMat=self.RangeMat, PeakValMat=self.PeakValMat, AngleMat=self.AngleMat, slope_calib=self.slope_calib,
                 fs_calib=self.fs_calib, interp=self.interp, samples=self.samples, tx_to_enable=self.tx_to_enable,
                 RxMismatch=(self.RxMismatch if self.RxMismatch is not None else np.zeros(0)),
                 TxMismatch=(self.TxMismatch if self.TxMismatch is not None else np.zeros(0)),
                 source=np.array(self.source), target_range_m=np.array(self.target_range_m if self.target_range_m is not None else np.nan))

    @classmethod
    def load(cls, path):
        z = np.load(path, allow_pickle=False)
        return cls(z["RangeMat"], z["PeakValMat"], z["AngleMat"], float(z["slope_calib"]), float(z["fs_calib"]), int(z["interp"]),
                   int(z["samples"]), z["tx_to_enable"], z["RxMismatch"] if z["RxMismatch"].size else None,
                   z["TxMismatch"] if z["TxMismatch"].size else None, str(z["source"]), float(z["target_range_m"]))

    def correction(self, fs, slope, phase_only=True):
        t_ref = self.tx_to_enable[0]
        n_ch = len(self.tx_to_enable)
        w = np.zeros((n_ch, self.RangeMat.shape[1]))
        ph = np.zeros((n_ch, self.RangeMat.shape[1]), dtype=complex)
        for c, t in enumerate(self.tx_to_enable):
            freq_calib = (self.RangeMat[t - 1, :] - self.RangeMat[t_ref - 1, 0]) * self.fs_calib / fs * slope / self.slope_calib
            w[c] = 2 * np.pi * freq_calib / (self.samples * self.interp)
            p = self.PeakValMat[t_ref - 1, 0] / self.PeakValMat[t - 1, :]
            ph[c] = p / np.abs(p) if phase_only else p
        return w, ph

    def apply_to_cube(self, cube, fs=8e6, slope=78.986e12, phase_only=True):
        cube = np.asarray(cube)
        n = cube.shape[1]
        w, ph = self.correction(fs, slope, phase_only)
        ns = np.arange(n)
        corr = np.exp(-1j * ns[None, :, None] * w.T[:, None, :]) * ph.T[:, None, :]
        return (cube * corr[:, :, :, None].astype(cube.dtype)).astype(cube.dtype)

    @classmethod
    def generate(cls, cube, target_range_m, fs, slope, interp=5, tx_to_enable=TX_TO_ENABLE, source=""):
        cube = np.asarray(cube)
        n_rx, n, n_ch, n_loops = cube.shape
        n_tx = len(tx_to_enable)
        win = matlab_hanning(n)
        win = win / np.sqrt(np.mean(win ** 2))
        lo = int(matlab_round(n * interp * ((target_range_m - 2) * 2 * slope / (SPEED_OF_LIGHT_TI * fs)) + 1))
        hi = int(matlab_round(n * interp * ((target_range_m + 2) * 2 * slope / (SPEED_OF_LIGHT_TI * fs)) + 1))
        lo = max(lo, 1)
        range_mat = np.zeros((n_tx, n_rx)); peak = np.zeros((n_tx, n_rx), dtype=complex); ang = np.zeros((n_tx, n_rx))
        rx_fft = np.zeros((n * interp, n_rx, n_tx), dtype=complex)
        for c in range(n_ch):
            t = tx_to_enable[c]
            for r in range(n_rx):
                x = cube[r, :, c, :].mean(axis=1) * win
                X = np.fft.fft(x, n * interp)
                seg = np.abs(X[lo - 1:hi])
                k = int(np.argmax(seg)) + lo
                range_mat[t - 1, r] = k
                peak[t - 1, r] = X[k - 1]
                ang[t - 1, r] = np.degrees(np.angle(X[k - 1]))
                rx_fft[:, r, t - 1] = X
        t_ref = tx_to_enable[0]
        rel_rx = ang - ang[:, :1]
        rx_mis = np.array([np.degrees(average_phase(np.radians(rel_rx[:, r]))) for r in range(n_rx)])
        rel_tx = ang - ang[t_ref - 1:t_ref, :]
        tx_mis = np.array([np.degrees(average_phase(np.radians(rel_tx[t, :]))) for t in range(n_tx)]).reshape(4, 3).T
        obj = cls(range_mat, peak, ang, slope, fs, interp, n, tx_to_enable, rx_mis, tx_mis, source, target_range_m)
        obj.Rx_fft = rx_fft
        return obj

    def estimated_target_range(self, range_resolution):
        return float(np.floor(np.mean(self.RangeMat) / self.interp) * range_resolution)

    def plot(self, path, fs=8e6, slope=78.986e12):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(1, 3, figsize=(15, 4))
        ax[0].plot(self.RangeMat.ravel(), ".-"); ax[0].set_title("peak range bin per (TX, RX)"); ax[0].grid(True)
        before = self.AngleMat - self.AngleMat[self.tx_to_enable[0] - 1, 0]
        ax[1].plot(np.degrees(np.angle(np.exp(1j * np.radians(before)))).ravel(), ".-"); ax[1].set_title("phase vs reference, before (deg)"); ax[1].grid(True)
        w, ph = self.correction(fs, slope, phase_only=True)
        after = np.zeros_like(self.AngleMat)
        for c, t in enumerate(self.tx_to_enable):
            after[t - 1] = np.degrees(np.angle(self.PeakValMat[t - 1] * ph[c]))
        ax[2].plot(after.ravel(), ".-"); ax[2].set_title("phase after correction (deg)"); ax[2].grid(True)
        fig.suptitle("calibration %s  target ~%s m" % (self.source, self.target_range_m))
        fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)
        return path
