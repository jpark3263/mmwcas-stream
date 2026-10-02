"""Offline test of tda2/follow_slot.py: frames written into a zero-filled preallocated file (and across a file rollover) arrive byte-exact and in order."""
import hashlib
import os
import queue
import shutil
import socket
import subprocess
import sys
import tempfile
import time

import numpy as np

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from tcp_tail_listener import TcpTailListener  # noqa: E402

FOLLOWER = os.path.join(ROOT, "tda2", "follow_slot.py")
LOOPBACK = socket.gethostbyname("localhost")


def payload(k, fb):
    return np.random.default_rng(1000 + k).bytes(fb)


def run_case(label, fb, times_s, workdir, port, poll="0.001", frames_per_file=0):
    n = len(times_s)
    data_path = os.path.join(workdir, "master_0000_data.bin")
    data_path1 = os.path.join(workdir, "master_0001_data.bin")
    log_path = os.path.join(workdir, "follow_master.log")
    for p in (data_path, data_path1, log_path):
        if os.path.exists(p):
            os.remove(p)
    expected = [hashlib.md5(payload(k, fb)).hexdigest() for k in range(n)]
    q = queue.Queue(maxsize=8192)
    lst = TcpTailListener("master", q, fb // 2, (LOOPBACK, port), emit_index=True)
    lst.start()
    time.sleep(0.3)
    proc = subprocess.Popen([sys.executable, FOLLOWER, data_path, LOOPBACK, str(port), "--frame-bytes", str(fb),
                             "--poll", poll, "--log", log_path, "--wait-file", "--idle-exit", "1.5"])
    time.sleep(0.4)
    with open(data_path, "wb") as f:
        f.write(b"\0" * ((n + 4) * fb + fb // 3))
    fd = open(data_path, "r+b")
    t_written = []
    t_start = time.perf_counter() + 0.3
    for k in range(n):
        while time.perf_counter() < t_start + times_s[k]:
            time.sleep(0.0005)
        if frames_per_file and k == frames_per_file:
            fd.close(); fd = open(data_path1, "wb")
        slot = k - frames_per_file if (frames_per_file and k >= frames_per_file) else k
        fd.seek(slot * fb); fd.write(payload(k, fb)); fd.flush()
        t_written.append(time.time())
    fd.close()
    rc = proc.wait(timeout=120)
    time.sleep(0.3)
    lst.stop()
    got = []
    while True:
        try:
            got.append(q.get_nowait())
        except queue.Empty:
            break
    bad = [k for k, (i, fr) in enumerate(got) if i != k or hashlib.md5(fr.tobytes()).hexdigest() != expected[k]]
    lines = [l.split() for l in open(log_path) if not l.startswith("#")]
    zeros = [l for l in lines if l[-1] == "ZERO"]
    assert rc == 0, "follower rc %d" % rc
    assert lst.stats["bytes"] == n * fb, (lst.stats["bytes"], n * fb)
    assert len(got) == n and not bad, (len(got), bad[:5])
    assert not zeros, "%d frames flagged ZERO" % len(zeros)
    lat = np.array([float(l[0]) for l in lines]) - np.array(t_written)
    print("  [%s] %d frames of %d B OK; write->sent latency ms: med %.1f p90 %.1f max %.1f"
          % (label, n, fb, np.median(lat) * 1e3, np.percentile(lat, 90) * 1e3, lat.max() * 1e3))


def test_follow_slot():
    wd = tempfile.mkdtemp(prefix="follow_slot_test_")
    try:
        run_case("fast", 49152, [k * 0.010 for k in range(300)], wd, 5611)
        run_case("rollover", 49152, [k * 0.010 for k in range(30)], wd, 5612, frames_per_file=12)
    finally:
        shutil.rmtree(wd, ignore_errors=True)


if __name__ == "__main__":
    test_follow_slot()
    print("all follower tests passed")
