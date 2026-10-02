"""Recorder -> replay round trip: replayed 16-RX cubes equal the live ones bit for bit and a frame the mux dropped is absent."""
import json
import os
import queue
import shutil
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from tcp_tail_listener import DEVICES, CaptureRecorder, CascadeFrameMux, ReplaySource, frame_bytes_per_device  # noqa: E402


def feed(queues, streams, fb, n, skip=()):
    for i in range(n):
        for d in DEVICES:
            if (d, i) in skip:
                continue
            queues[d].put((i, np.frombuffer(streams[d][i * fb:(i + 1) * fb], dtype="<i2")))
        time.sleep(0.005)


def collect(out, expect, timeout=5.0):
    got = {}
    t_end = time.time() + timeout
    while len(got) < expect and time.time() < t_end:
        try:
            idx, cube = out.get(timeout=0.2)
            got[idx] = cube
        except queue.Empty:
            pass
    return got


def test_record_replay_roundtrip():
    S, C, L, N = 16, 12, 1, 20
    fb = frame_bytes_per_device(S, C, L)
    rng = np.random.default_rng(7)
    streams = {d: rng.integers(-32768, 32767, size=fb // 2 * N, dtype=np.int64).astype("<i2").tobytes() for d in DEVICES}
    root = tempfile.mkdtemp(prefix="rec_test_")
    try:
        q1 = {d: queue.Queue() for d in DEVICES}
        out1 = queue.Queue()
        rec = CaptureRecorder("t1", S, C, L, period_ms=20, tag="TEST", root=root)
        mux1 = CascadeFrameMux(q1, out1, S, C, L, max_age_s=0.05, raw_sink=rec.on_set)
        mux1.start()
        feed(q1, streams, fb, N, skip={("slave1", 7)})
        live = collect(out1, N - 1)
        time.sleep(0.3)
        mux1.stop(); rec.close()
        assert sorted(live) == [i for i in range(N) if i != 7], sorted(live)
        cfg = json.load(open(os.path.join(root, "t1", "config.json")))
        assert cfg["frames_recorded"] == N - 1 and cfg["frame_bytes_total"] == 4 * fb and cfg["period_ms"] == 20
        rows = np.loadtxt(os.path.join(root, "t1", "frames.csv"), delimiter=",", skiprows=1, ndmin=2)
        assert rows[:, 0].astype(int).tolist() == [i for i in range(N) if i != 7]
        assert os.path.getsize(os.path.join(root, "t1", "frames.bin")) == (N - 1) * 4 * fb
        raw = open(os.path.join(root, "t1", "frames.bin"), "rb").read()
        assert raw[:fb] == streams["master"][:fb] and raw[3 * fb:4 * fb] == streams["slave3"][:fb]
        q2 = {d: queue.Queue() for d in DEVICES}
        out2 = queue.Queue()
        mux2 = CascadeFrameMux(q2, out2, S, C, L)
        mux2.start()
        src = ReplaySource("t1", q2, root=root, speed=0)
        src.start(); src.join(10)
        rep = collect(out2, N - 1)
        mux2.stop()
        assert sorted(rep) == sorted(live)
        for k in live:
            np.testing.assert_array_equal(rep[k], live[k])
        print("  record/replay round trip OK: %d frames, %d B" % (len(rep), len(raw)))
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    test_record_replay_roundtrip()
    print("all recorder tests passed")
