"""numpy port of TI's cascade processing chain (range FFT, Doppler FFT, range-Doppler and range-azimuth maps) on the mux cube [16 RX, samples, chirps, loops]."""
import os
import time

import numpy as np

from .geometry import CascadeGeometry, reorder_rx_to_physical

SPEED_OF_LIGHT_TI = 3e8


def matlab_hanning(n):
    k = np.arange(1, n + 1)
    return 0.5 * (1.0 - np.cos(2.0 * np.pi * k / (n + 1)))


class RadarParams:
    def __init__(self, samples=256, chirps=12, loops=1, start_freq_hz=77e9, slope_hz_per_s=78.986e12, fs_hz=8e6,
                 idle_s=5e-6, adc_start_s=6e-6, ramp_end_s=40e-6, range_fft=None, doppler_fft=None, angle_fft=256):
        self.samples, self.chirps, self.loops = samples, chirps, loops
        self.fs = fs_hz
        self.slope = slope_hz_per_s
        self.range_fft = range_fft or (1 << int(np.ceil(np.log2(samples))))
        self.doppler_fft = doppler_fft or (1 << int(np.ceil(np.log2(max(loops, 1)))))
        self.angle_fft = angle_fft
        ramp_time = samples / fs_hz
        bandwidth = slope_hz_per_s * ramp_time
        self.chirp_interval = ramp_end_s + idle_s
        self.carrier_hz = start_freq_hz + (adc_start_s + ramp_time / 2) * slope_hz_per_s
        self.lambda_m = SPEED_OF_LIGHT_TI / self.carrier_hz
        self.range_resolution = SPEED_OF_LIGHT_TI / 2 / bandwidth
        self.range_bin_size = self.range_resolution * samples / self.range_fft
        self.velocity_resolution = self.lambda_m / (2 * loops * self.chirp_interval * chirps)
        self.velocity_bin_size = self.velocity_resolution * loops / self.doppler_fft
        self.center_freq_ghz = start_freq_hz / 1e9 + samples / (fs_hz / 1e3) * (slope_hz_per_s / 1e12) / 2


class Pipeline:
    def __init__(self, params, geometry=None, clutter_remove=False, background_frames=0):
        self.p = params
        self.geo = geometry or CascadeGeometry(center_freq_ghz=params.center_freq_ghz)
        self.win = matlab_hanning(params.samples).astype(np.float32)
        self.clutter_remove = clutter_remove
        self.background_frames = background_frames
        self.bg_static = None
        self.bg_enabled = True
        self.reset_background()
        self.timing = {}
        n = self.p.angle_fft
        self.sin_theta = np.clip(-2.0 * (np.arange(-n // 2, n // 2) / n) / (2 * self.geo.d_optimal), -1, 1)
        self.angle_deg = np.degrees(np.arcsin(self.sin_theta))
        self.range_axis_m = np.arange(self.p.range_fft) * self.p.range_bin_size

    def reset_background(self):
        self._bg = []
        self._bg_sum = None

    def frame_to_tx_cubes(self, cube):
        t = time.perf_counter()
        x = reorder_rx_to_physical(np.asarray(cube), axis=0)
        x = np.transpose(x, (1, 3, 0, 2))
        self.timing["reorder"] = time.perf_counter() - t
        return x

    def range_fft(self, adc):
        t = time.perf_counter()
        x = adc - adc.mean(axis=0, keepdims=True)
        x = x * self.win[:, None, None, None]
        out = np.fft.fft(x, n=self.p.range_fft, axis=0)
        self.timing["range_fft"] = time.perf_counter() - t
        return out

    def doppler_fft(self, rng):
        t = time.perf_counter()
        if self.clutter_remove and rng.shape[1] > 1:
            rng = rng - rng.mean(axis=1, keepdims=True)
        out = np.fft.fftshift(np.fft.fft(rng, n=self.p.doppler_fft, axis=1), axes=1) if rng.shape[1] > 1 else rng
        r, d, nrx, ntx = out.shape
        out = out.reshape(r, d, nrx * ntx, order="F")
        self.timing["doppler_fft"] = time.perf_counter() - t
        return out

    def rd_map(self, dop):
        t = time.perf_counter()
        out = 10 * np.log10(np.sum(np.abs(dop) ** 2, axis=2) + 1)
        self.timing["rd_map"] = time.perf_counter() - t
        return out

    def _subtract_rolling_background(self, x):
        x_out = x - (self._bg_sum / len(self._bg)).astype(x.dtype) if self._bg else x
        self._bg.append(x)
        self._bg_sum = (self._bg_sum + x.astype(np.complex128)) if self._bg_sum is not None and len(self._bg) > 1 else x.astype(np.complex128)
        if len(self._bg) > self.background_frames:
            self._bg_sum = self._bg_sum - self._bg.pop(0).astype(np.complex128)
        return x_out

    def ra_map(self, dop, doppler_bin=None, db=True):
        t = time.perf_counter()
        if doppler_bin is None:
            doppler_bin = dop.shape[1] // 2 if dop.shape[1] > 1 else 0
        x = dop[:, doppler_bin, self.geo.antenna_azimuthonly]
        self.last_azimuth_input = x
        single_doppler_bin = dop.shape[1] == 1
        if self.bg_enabled and self.bg_static is not None and single_doppler_bin:
            x = x - self.bg_static
        elif self.bg_enabled and self.background_frames and single_doppler_bin:
            x = self._subtract_rolling_background(x)
        spec = np.fft.fftshift(np.fft.fft(x, n=self.p.angle_fft, axis=1), axes=1)
        mag = np.abs(spec)
        out = 20 * np.log10(mag + 1e-3) if db else mag
        self.timing["ra_map"] = time.perf_counter() - t
        return out

    def background_from_frames(self, cubes):
        acc = None; n = 0
        for cube in cubes:
            dop = self.doppler_fft(self.range_fft(self.frame_to_tx_cubes(cube)))
            x = dop[:, dop.shape[1] // 2 if dop.shape[1] > 1 else 0, self.geo.antenna_azimuthonly]
            acc = x.astype(np.complex128) if acc is None else acc + x
            n += 1
        self.bg_static = (acc / n).astype(np.complex64) if n else None
        return n

    def process(self, cube, want_rd=True):
        t0 = time.perf_counter()
        adc = self.frame_to_tx_cubes(cube)
        rng = self.range_fft(adc)
        dop = self.doppler_fft(rng)
        rd = self.rd_map(dop) if want_rd and dop.shape[1] > 1 else None
        ra = self.ra_map(dop)
        self.timing["total"] = time.perf_counter() - t0
        return dict(range=rng, doppler=dop, rd=rd, ra=ra, timing_ms={k: v * 1e3 for k, v in self.timing.items()})


def tdm_doppler_compensate(dop, num_tx, num_rx=16):
    dop = np.asarray(dop)
    n_dop = dop.shape[1]
    if n_dop <= 1:
        return dop
    delta_phi = 2 * np.pi * (np.arange(n_dop) - n_dop // 2) / (num_tx * n_dop)
    tx_slot = np.repeat(np.arange(num_tx), num_rx)
    corr = np.exp(-1j * np.outer(delta_phi, tx_slot))
    return dop * corr[None, :, :].astype(dop.dtype)


def doa_beamforming_fft_2d(sig, geometry, angle_fft=256):
    D = geometry.D + 1
    ap_az, ap_el = int(D[:, 0].max()), int(D[:, 1].max())
    sig_2d = np.zeros((ap_az, ap_el), dtype=complex)
    for line in range(1, ap_el + 1):
        ind = np.where(D[:, 1] == line)[0]
        if not len(ind):
            continue
        d_sel = D[ind, 0]
        _, first = np.unique(d_sel, return_index=True)
        sig_2d[d_sel[first] - 1, line - 1] = np.asarray(sig)[ind[first]]
    spec_1d = np.fft.fftshift(np.fft.fft(sig_2d, angle_fft, axis=0), axes=0)
    spec_2d = np.fft.fftshift(np.fft.fft(spec_1d, angle_fft, axis=1), axes=1)
    w = np.arange(-np.pi, np.pi, 2 * np.pi / angle_fft)
    sin_ax = np.clip(w / (2 * np.pi * geometry.d_optimal), -1, 1)
    return spec_2d, sin_ax, sin_ax.copy()


def read_tda_frame(folder, frame_idx, samples, chirps, loops, devices=("master", "slave1", "slave2", "slave3"), file_idx=0):
    fb = samples * chirps * loops * 4 * 2 * 2
    cubes = []
    for d in devices:
        with open(os.path.join(folder, "%s_%04d_data.bin" % (d, file_idx)), "rb") as f:
            f.seek(frame_idx * fb)
            raw = np.frombuffer(f.read(fb), dtype="<i2")
        c = raw[0::2].astype(np.float32) + 1j * raw[1::2].astype(np.float32)
        cubes.append(np.reshape(c, (4, samples, chirps, loops), order="F"))
    return np.concatenate(cubes, axis=0).astype(np.complex64)
