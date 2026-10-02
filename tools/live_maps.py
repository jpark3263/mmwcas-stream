"""Live range-azimuth / range-Doppler viewer: four listeners (or a replayed recording) -> mux -> DSP worker -> pyqtgraph GUI."""
import argparse
import json
import os
import queue
import sys
import threading as th
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cfg  # noqa: E402
sys.path.insert(0, cfg.ROOT)
from tcp_tail_listener import (CAPTURES, DEVICES, CaptureRecorder, CascadeFrameMux, ReplaySource, TcpTailListener,  # noqa: E402
                               frame_bytes_per_device)
from cascade_dsp.geometry import CascadeGeometry  # noqa: E402
from cascade_dsp.pipeline import Pipeline, RadarParams  # noqa: E402
from cascade_dsp.calibration import CalibrationMatrix  # noqa: E402

LOGS = os.path.join(cfg.ROOT, "logs")
QUIT_FLAG = os.path.join(LOGS, "viewer.quit")


class DspWorker(th.Thread):
    def __init__(self, in_queue, pipeline, max_backlog=3):
        super().__init__(name="dsp", daemon=True)
        self.q = in_queue
        self.pipe = pipeline
        self.max_backlog = max_backlog
        self.lock = th.Lock()
        self.latest = None
        self.stats = dict(processed=0, dropped_backlog=0, last_ms=0.0, ms_hist=[])
        self._running = True
        self.calib = None
        self.calib_on = False
        self.freeze = False

    def stop(self):
        self._running = False

    def run(self):
        while self._running:
            try:
                idx, cube = self.q.get(timeout=0.05)
            except queue.Empty:
                continue
            while self.q.qsize() > self.max_backlog:
                try:
                    idx, cube = self.q.get_nowait()
                    self.stats["dropped_backlog"] += 1
                except queue.Empty:
                    break
            if self.freeze:
                continue
            t0 = time.perf_counter()
            if self.calib is not None and self.calib_on:
                cube = self.calib.apply_to_cube(cube)
            res = self.pipe.process(cube, want_rd=True)
            ms = (time.perf_counter() - t0) * 1e3
            with self.lock:
                self.latest = (idx, res)
                self.stats["processed"] += 1
                self.stats["last_ms"] = ms
                self.stats["ms_hist"].append(ms)
                if len(self.stats["ms_hist"]) > 200:
                    self.stats["ms_hist"].pop(0)


def recording_frames(name):
    cdir = os.path.join(CAPTURES, name)
    c = json.load(open(os.path.join(cdir, "config.json")))
    fbb = c["frame_bytes_per_device"]
    nfr = int(os.path.getsize(os.path.join(cdir, "frames.bin")) // (4 * fbb))
    with open(os.path.join(cdir, "frames.bin"), "rb") as f:
        for _ in range(nfr):
            raw = np.frombuffer(f.read(4 * fbb), dtype="<i2")
            parts = []
            for k in range(4):
                blk = raw[k * fbb // 2:(k + 1) * fbb // 2]
                z = blk[0::2].astype(np.float32) + 1j * blk[1::2].astype(np.float32)
                parts.append(np.reshape(z, (4, c["samples"], c["chirps"], c["loops"]), order="F"))
            yield np.concatenate(parts, axis=0).astype(np.complex64)


def main():
    c = cfg.load()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--samples", type=int, default=c["capture"]["samples"])
    ap.add_argument("--chirps", type=int, default=c["capture"]["chirps"])
    ap.add_argument("--loops", type=int, default=c["capture"]["loops"])
    ap.add_argument("--period-ms", type=float, default=c["capture"]["period_ms"])
    ap.add_argument("--replay", default=None, help="captures/<name>/ instead of the radar")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--record-capture", default=None, help="record the muxed frames to captures/<name>/")
    ap.add_argument("--calib", default=os.path.join(cfg.ROOT, "calib.npz"), help="calibration file (loaded if it exists)")
    ap.add_argument("--max-age", type=float, default=0.25)
    ap.add_argument("--max-backlog", type=int, default=3)
    ap.add_argument("--az-limit", type=float, default=60.0)
    ap.add_argument("--db-floor", type=float, default=40.0)
    ap.add_argument("--db-span", type=float, default=100.0)
    ap.add_argument("--flip-azimuth", action="store_true")
    ap.add_argument("--background", action="store_true", help="start with background subtraction on (loops == 1)")
    ap.add_argument("--bg-frames", type=int, default=250, help="rolling-mean window in frames")
    ap.add_argument("--bg-from", default=None, help="fixed background = mean over captures/<name>/")
    ap.add_argument("--exit-after", type=float, default=0, help="quit after N s (0 = run until closed)")
    ap.add_argument("--gui-fps", type=float, default=25.0)
    ap.add_argument("--eta", type=float, default=0, help="seconds until the first live frame is expected (title countdown)")
    ap.add_argument("--arrival-log", default=None, help="CSV of every complete 16-RX set leaving the mux: frame_idx,t_wall")
    a = ap.parse_args()

    import pyqtgraph as pg
    from pyqtgraph.Qt import QtCore, QtGui, QtWidgets
    import signal
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    queues = {d: queue.Queue(maxsize=1024) for d in DEVICES}
    listeners = {}
    src = None
    if a.replay:
        src = ReplaySource(a.replay, queues, speed=a.speed, loop=True)
        a.samples, a.chirps, a.loops = src.config["samples"], src.config["chirps"], src.config["loops"]
        if src.config.get("period_ms"):
            a.period_ms = float(src.config["period_ms"])
    fb = frame_bytes_per_device(a.samples, a.chirps, a.loops)
    if not a.replay:
        for dev, port in zip(DEVICES, c["pc"]["ports"]):
            lst = TcpTailListener(dev, queues[dev], fb // 2, (c["pc"]["bind"], port), emit_index=True)
            lst.start()
            listeners[dev] = lst
    mux_out = queue.Queue(maxsize=64)
    rec = CaptureRecorder(a.record_capture, a.samples, a.chirps, a.loops, period_ms=a.period_ms) if a.record_capture else None
    arr = open(a.arrival_log, "w", buffering=1) if a.arrival_log else None
    if arr:
        arr.write("frame_idx,t_wall\n")

    def raw_sink(idx, parts):
        if arr:
            arr.write("%d,%.6f\n" % (idx, time.time()))
        if rec:
            rec.on_set(idx, parts)
    mux = CascadeFrameMux(queues, mux_out, a.samples, a.chirps, a.loops, max_age_s=a.max_age, raw_sink=(raw_sink if (rec or arr) else None))
    mux.start()
    if src:
        src.start()

    params = RadarParams(samples=a.samples, chirps=a.chirps, loops=a.loops)
    geo = CascadeGeometry(center_freq_ghz=params.center_freq_ghz)
    pipe = Pipeline(params, geo, background_frames=a.bg_frames)
    pipe.bg_enabled = bool(a.background)
    bg_state = "rolling %d frames" % a.bg_frames
    if a.bg_from:
        n_bg = pipe.background_from_frames(recording_frames(a.bg_from))
        bg_state = "fixed from %s (%d frames)" % (a.bg_from, n_bg)
    worker = DspWorker(mux_out, pipe, max_backlog=a.max_backlog)
    calib_state = "uncalibrated"
    if os.path.exists(a.calib):
        try:
            worker.calib = CalibrationMatrix.load(a.calib)
            worker.calib_on = True
            calib_state = "calibrated (%s)" % os.path.basename(a.calib)
        except Exception as e:
            calib_state = "calib load failed: %s" % e
    worker.start()

    range_m = pipe.range_axis_m
    angle_deg = pipe.angle_deg.copy()
    if a.flip_azimuth:
        angle_deg = -angle_deg
    r_lo, r_hi = 3, params.range_fft // 2

    app = pg.mkQApp("mmwcas-stream live maps")
    win = QtWidgets.QMainWindow()
    central = QtWidgets.QWidget(); win.setCentralWidget(central)
    vbox = QtWidgets.QVBoxLayout(central)
    glw = pg.GraphicsLayoutWidget()
    vbox.addWidget(glw, stretch=1)
    ctrl = QtWidgets.QHBoxLayout(); vbox.addLayout(ctrl)
    cb_bg = QtWidgets.QCheckBox("background subtraction"); cb_bg.setChecked(bool(a.background)); ctrl.addWidget(cb_bg)
    cb_cal = QtWidgets.QCheckBox("calibration"); cb_cal.setChecked(worker.calib_on); cb_cal.setEnabled(worker.calib is not None); ctrl.addWidget(cb_cal)
    cb_frz = QtWidgets.QCheckBox("freeze"); ctrl.addWidget(cb_frz)
    cb_flip = QtWidgets.QCheckBox("flip azimuth"); cb_flip.setChecked(a.flip_azimuth); ctrl.addWidget(cb_flip)
    ctrl.addWidget(QtWidgets.QLabel("dB floor"))
    sp_floor = QtWidgets.QDoubleSpinBox(); sp_floor.setRange(-50, 200); sp_floor.setValue(a.db_floor); sp_floor.setSingleStep(2); ctrl.addWidget(sp_floor)
    ctrl.addWidget(QtWidgets.QLabel("span"))
    sp_span = QtWidgets.QDoubleSpinBox(); sp_span.setRange(5, 150); sp_span.setValue(a.db_span); sp_span.setSingleStep(5); ctrl.addWidget(sp_span)
    btn_shot = QtWidgets.QPushButton("screenshot -> logs/"); ctrl.addWidget(btn_shot)
    ctrl.addStretch(1)

    p_ra = glw.addPlot(title="range-azimuth (dB)")
    img_ra = pg.ImageItem(); p_ra.addItem(img_ra)
    p_ra.setLabel("bottom", "azimuth", units="deg"); p_ra.setLabel("left", "range", units="m")
    cmap = pg.colormap.get("viridis"); img_ra.setLookupTable(cmap.getLookupTable(0.0, 1.0, 256))
    p_prof = glw.addPlot(title="boresight range profile (dB)")
    p_prof.setLabel("bottom", "range", units="m"); p_prof.setLabel("left", "dB"); p_prof.showGrid(x=True, y=True)
    curve_prof = p_prof.plot(pen="y")
    prof_auto = {"on": False}

    def apply_db_range():
        floor, span = sp_floor.value(), sp_span.value()
        if prof_auto["on"]:
            p_prof.enableAutoRange(axis="y", enable=True)
            p_prof.setTitle("boresight range profile (dB)  --  y AUTOSCALE ('a' = fixed)")
        else:
            p_prof.enableAutoRange(axis="y", enable=False)
            p_prof.setYRange(floor, floor + span, padding=0)
            p_prof.setTitle("boresight range profile (dB)  --  y fixed %.0f..%.0f dB ('a' = autoscale)" % (floor, floor + span))
    apply_db_range()
    sp_floor.valueChanged.connect(lambda _v: apply_db_range())
    sp_span.valueChanged.connect(lambda _v: apply_db_range())

    def toggle_prof_auto():
        prof_auto["on"] = not prof_auto["on"]
        apply_db_range()
    img_rd = None
    if a.loops > 1:
        glw.nextRow()
        p_rd = glw.addPlot(title="range-Doppler (dB)", colspan=2)
        img_rd = pg.ImageItem(); p_rd.addItem(img_rd); img_rd.setLookupTable(cmap.getLookupTable(0.0, 1.0, 256))
        p_rd.setLabel("bottom", "velocity", units="m/s"); p_rd.setLabel("left", "range", units="m")
        vel_axis = (np.arange(params.doppler_fft) - params.doppler_fft // 2) * params.velocity_bin_size
    win.resize(1400, 800 if a.loops > 1 else 560)
    win.show()

    state = dict(t0=time.perf_counter(), last_idx=-1, drawn=0, t_last_title=0.0, frames_in_prev=0, proc_prev=0,
                 t_rate=time.perf_counter(), t_quit_check=0.0, live_announced=False)
    ts_tag = time.strftime("%Y%m%d_%H%M%S")

    def screenshot(tag="manual"):
        os.makedirs(LOGS, exist_ok=True)
        path = os.path.join(LOGS, "live_maps_%s_%s.png" % (ts_tag, tag))
        win.grab().save(path)
        print("[live_maps] screenshot saved:", path, flush=True)
        return path
    btn_shot.clicked.connect(lambda: screenshot("manual"))

    def on_bg(v):
        pipe.bg_enabled = bool(v)
        pipe.reset_background()
    cb_bg.toggled.connect(on_bg)
    cb_cal.toggled.connect(lambda v: setattr(worker, "calib_on", bool(v)))
    cb_frz.toggled.connect(lambda v: setattr(worker, "freeze", bool(v)))
    for key, fn in (("B", cb_bg.toggle), ("F", cb_flip.toggle), ("Space", cb_frz.toggle), ("S", lambda: screenshot("key")), ("A", toggle_prof_auto)):
        sc = QtWidgets.QShortcut(QtGui.QKeySequence(key), win)
        sc.activated.connect(fn)

    def current_axes():
        ang = -angle_deg if (cb_flip.isChecked() != a.flip_azimuth) else angle_deg
        ok = np.abs(ang) <= a.az_limit
        cols = np.where(ok)[0][np.argsort(ang[ok])]
        return cols, ang[cols]

    def quit_requested(t):
        if t - state["t_quit_check"] < 0.5:
            return False
        state["t_quit_check"] = t
        if not os.path.exists(QUIT_FLAG):
            return False
        try:
            os.remove(QUIT_FLAG)
        except OSError:
            pass
        print("[live_maps] quit flag seen -> closing", flush=True)
        return True

    def update():
        with worker.lock:
            latest = worker.latest
        if latest is not None and latest[0] != state["last_idx"]:
            idx, res = latest
            state["last_idx"] = idx
            state["drawn"] += 1
            cols, azx = current_axes()
            ra = res["ra"][r_lo:r_hi, :][:, cols]
            floor, span = sp_floor.value(), sp_span.value()
            img_ra.setImage(ra.T, autoLevels=False, levels=(floor, floor + span))
            img_ra.setRect(QtCore.QRectF(azx[0], range_m[r_lo], azx[-1] - azx[0], range_m[r_hi - 1] - range_m[r_lo]))
            bc = int(np.argmin(np.abs(azx)))
            curve_prof.setData(range_m[r_lo:r_hi], ra[:, bc])
            if img_rd is not None and res["rd"] is not None:
                rd = res["rd"][r_lo:r_hi, :]
                img_rd.setImage(rd.T, autoLevels=False, levels=(floor, floor + span))
                img_rd.setRect(QtCore.QRectF(vel_axis[0], range_m[r_lo], vel_axis[-1] - vel_axis[0], range_m[r_hi - 1] - range_m[r_lo]))
        t = time.perf_counter()
        if quit_requested(t) or (a.exit_after and t - state["t0"] >= a.exit_after):
            app.quit()
            return
        if state["drawn"] == 0 and a.eta and t - state["t_last_title"] >= 0.25:
            left = a.eta - (t - state["t0"])
            win.setWindowTitle("mmwcas-stream | WAITING FOR THE CAPTURE | first frames expected in %s" % ("%.0f s" % left if left > 0 else "a moment"))
            p_ra.setTitle("waiting ... T-%.0f s" % max(left, 0) if left > -5 else "waiting for frames ...")
            state["t_last_title"] = t
            return
        if state["drawn"] == 1 and not state["live_announced"]:
            state["live_announced"] = True
            p_ra.setTitle("range-azimuth (dB)  --  LIVE")
        if t - state["t_last_title"] >= 0.5:
            dt = t - state["t_rate"]
            fin = mux.stats["emitted"]
            fps_in = (fin - state["frames_in_prev"]) / dt if dt > 0 else 0
            fps_proc = (worker.stats["processed"] - state["proc_prev"]) / dt if dt > 0 else 0
            state["frames_in_prev"], state["proc_prev"], state["t_rate"] = fin, worker.stats["processed"], t
            ms = np.median(worker.stats["ms_hist"]) if worker.stats["ms_hist"] else 0
            win.setWindowTitle("mmwcas-stream | %s | %.0f ms / %d loop(s), 12 TX x 16 RX | in %.1f fps, processed %.1f fps, drawn %d | "
                               "mux drops %d (gaps %d) | backlog drops %d | pipeline %.1f ms | %s | bg %s%s%s"
                               % ("replay " + a.replay if a.replay else "LIVE", a.period_ms, a.loops, fps_in, fps_proc, state["drawn"],
                                  mux.stats["incomplete_dropped"], mux.stats["gaps"], worker.stats["dropped_backlog"], ms, calib_state,
                                  ("ON: " + bg_state) if cb_bg.isChecked() else "OFF (raw)", " | az FLIPPED" if cb_flip.isChecked() else "",
                                  " | FROZEN" if cb_frz.isChecked() else ""))
            print("[live_maps] idx=%d in=%.1f fps proc=%.1f fps drawn=%d mux=%s pipeline=%.1f ms" % (
                state["last_idx"], fps_in, fps_proc, state["drawn"], {k: mux.stats[k] for k in ("emitted", "incomplete_dropped", "gaps")}, ms), flush=True)
            state["t_last_title"] = t

    timer = QtCore.QTimer(); timer.timeout.connect(update); timer.start(int(1000 / a.gui_fps))
    try:
        app.exec() if hasattr(app, "exec") else app.exec_()
    finally:
        worker.stop(); mux.stop()
        if src: src.stop()
        for lst in listeners.values():
            lst.stop()
        if rec: rec.close()
        if arr: arr.close()
        print("[live_maps] exit: drawn %d, processed %d, mux %s" % (state["drawn"], worker.stats["processed"], mux.stats), flush=True)


if __name__ == "__main__":
    main()
