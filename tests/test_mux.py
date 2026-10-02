"""The listener and the frame mux must reproduce TI's MATLAB reader (read_ADC_bin_TDA2_separateFiles.m) on synthetic byte streams."""
import os
import queue
import socket
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from tcp_tail_listener import (CascadeFrameMux, DEVICES, TcpTailListener, device_frame_to_cube,  # noqa: E402
                               frame_bytes_per_device, to_matlab_layout)

LOOPBACK = socket.gethostbyname("localhost")


def matlab_readBinFile_reference(raw_bytes, S, C, L, RX=4):
    u = np.frombuffer(raw_bytes, dtype="<u2").astype(np.int64)
    neg = (u >> 15) & 1
    v = u - neg * 65536
    cplx = v[0::2] + 1j * v[1::2]
    out = np.zeros((RX, S, C, L), dtype=np.complex128)
    k = 0
    for l in range(L):
        for c in range(C):
            for s in range(S):
                for r in range(RX):
                    out[r, s, c, l] = cplx[k]
                    k += 1
    assert k == len(cplx)
    return np.transpose(out, (1, 3, 0, 2))


def make_stream(rng, S, C, L, n_frames):
    fb = frame_bytes_per_device(S, C, L)
    return rng.integers(-32768, 32767, size=fb // 2 * n_frames, dtype=np.int64).astype("<i2").tobytes()


def test_device_reshape_matches_matlab():
    rng = np.random.default_rng(1)
    S, C, L = 16, 3, 2
    raw = make_stream(rng, S, C, L, 1)
    ref = matlab_readBinFile_reference(raw, S, C, L)
    cube = device_frame_to_cube(np.frombuffer(raw, dtype="<i2"), S, C, L)
    assert cube.shape == (4, S, C, L)
    np.testing.assert_array_equal(np.transpose(cube, (1, 3, 0, 2)), ref)


def test_mux_reproduces_matlab_16rx():
    rng = np.random.default_rng(2)
    S, C, L, N = 8, 12, 2, 3
    fb = frame_bytes_per_device(S, C, L)
    streams = {d: make_stream(rng, S, C, L, N) for d in DEVICES}
    queues = {d: queue.Queue() for d in DEVICES}
    out = queue.Queue()
    mux = CascadeFrameMux(queues, out, S, C, L)
    nxt = {d: 0 for d in DEVICES}
    while any(nxt[d] < N for d in DEVICES):
        d = DEVICES[int(rng.integers(0, 4))]
        if nxt[d] < N:
            i = nxt[d]
            queues[d].put((i, np.frombuffer(streams[d][i * fb:(i + 1) * fb], dtype="<i2")))
            nxt[d] += 1
    mux.start()
    got = {}
    t_end = time.time() + 5
    while len(got) < N and time.time() < t_end:
        try:
            idx, cube = out.get(timeout=0.5)
            got[idx] = cube
        except queue.Empty:
            pass
    mux.stop()
    assert sorted(got) == list(range(N)), sorted(got)
    for i in range(N):
        cube = got[i]
        assert cube.shape == (16, S, C, L)
        expected = np.zeros((S, L, 16, C), dtype=np.complex128)
        for k, d in enumerate(DEVICES):
            expected[:, :, 4 * k:4 * k + 4, :] = matlab_readBinFile_reference(streams[d][i * fb:(i + 1) * fb], S, C, L)
        np.testing.assert_array_equal(to_matlab_layout(cube), expected)
    assert mux.stats["gaps"] == 0 and mux.stats["stale"] == 0


def test_listener_end_to_end_over_localhost():
    rng = np.random.default_rng(3)
    S, C, L, N = 32, 12, 1, 5
    fb = frame_bytes_per_device(S, C, L)
    raw = make_stream(rng, S, C, L, N)
    q = queue.Queue()
    lst = TcpTailListener("t", q, fb // 2, (LOOPBACK, 0), emit_index=True)
    lst.start()
    port = 0
    for _ in range(200):
        if lst.sock is not None:
            try:
                port = lst.sock.getsockname()[1]
            except OSError:
                port = 0
            if port:
                break
        time.sleep(0.02)
    assert port
    c = socket.create_connection((LOOPBACK, port))
    pos = 0
    while pos < len(raw):
        n = int(rng.integers(1, 7000))
        c.sendall(raw[pos:pos + n])
        pos += n
    c.close()
    frames = []
    t_end = time.time() + 5
    while len(frames) < N and time.time() < t_end:
        try:
            frames.append(q.get(timeout=0.5))
        except queue.Empty:
            pass
    lst.stop()
    assert [i for i, _ in frames] == list(range(N))
    for i, f in frames:
        np.testing.assert_array_equal(f, np.frombuffer(raw[i * fb:(i + 1) * fb], dtype="<i2"))
    assert lst.stats["frames"] == N and lst.stats["bytes"] == len(raw)


def test_mux_drops_incomplete_sets_without_blocking():
    S, C, L, N = 8, 12, 1, 10
    fb = frame_bytes_per_device(S, C, L)
    rng = np.random.default_rng(4)
    streams = {d: make_stream(rng, S, C, L, N) for d in DEVICES}
    queues = {d: queue.Queue() for d in DEVICES}
    out = queue.Queue()
    mux = CascadeFrameMux(queues, out, S, C, L, max_age_s=0.1)
    mux.start()
    for i in range(N):
        for d in DEVICES:
            if d == "slave2" and (i in (3, 4) or i > 6):
                continue
            queues[d].put((i, np.frombuffer(streams[d][i * fb:(i + 1) * fb], dtype="<i2")))
        time.sleep(0.02)
    time.sleep(0.5)
    mux.stop()
    got = []
    while True:
        try:
            got.append(out.get_nowait()[0])
        except queue.Empty:
            break
    assert got == [0, 1, 2, 5, 6], got
    assert mux.stats["incomplete_dropped"] == 5, mux.stats
    assert mux.stats["missing_by_dev"]["slave2"] == 5 and mux.stats["missing_by_dev"]["master"] == 0, mux.stats
    assert mux.stats["gaps"] == 2, mux.stats
    assert not mux.pending, mux.pending


if __name__ == "__main__":
    test_device_reshape_matches_matlab()
    test_mux_reproduces_matlab_16rx()
    test_listener_end_to_end_over_localhost()
    test_mux_drops_incomplete_sets_without_blocking()
    print("all mux tests passed")
