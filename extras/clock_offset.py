"""Estimates the offset between the PC clock and the board's time.time() / uptime over the board's TCP time server (fallback: ssh), prints one '# clock_offset' line."""
import argparse
import os
import socket
import subprocess
import sys
import time

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import cfg  # noqa: E402

BOARD = cfg.get("tda.ip")
SSH = ["sh", os.path.join(ROOT, "tools", "tda2_ssh.sh")]
CODE = "import time\nprint('%.6f' % time.time())\nprint(open('/proc/uptime').read().split()[0])\n"


def sample_ssh():
    t0 = time.time()
    r = subprocess.run(SSH + ["python -"], input=CODE, capture_output=True, text=True, timeout=20)
    out = r.stdout.split()
    if len(out) < 2:
        raise RuntimeError("bad reply: stdout=%r stderr=%r" % (r.stdout, r.stderr))
    t1 = time.time()
    return t0, t1, float(out[0]), float(out[1])


def samples_tcp(n, port):
    s = socket.create_connection((BOARD, port), timeout=3)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    f = s.makefile("r")
    res = []
    for _ in range(n):
        t0 = time.time()
        s.sendall(b"t\n")
        line = f.readline()
        t1 = time.time()
        p = line.split()
        res.append((t0, t1, float(p[0]), float(p[1])))
        time.sleep(0.01)
    s.close()
    return res


def estimate(samples):
    rtt, t0, t1, tb, up = min((t1 - t0, t0, t1, tb, up) for (t0, t1, tb, up) in samples)
    mid = (t0 + t1) / 2
    return dict(pc_wall=mid, board_time=tb, uptime=up, offset=tb - mid, up_offset=up - mid, rtt_ms=rtt * 1e3)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--label", default="")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--port", type=int, default=5010)
    a = ap.parse_args()
    via = "tcp"
    try:
        samples = samples_tcp(a.n, a.port)
    except Exception as e:
        via = "ssh"
        try:
            samples = [sample_ssh() for _ in range(min(a.n, 5))]
        except Exception as e2:
            print("# clock_offset %s ERROR tcp=%s ssh=%s" % (a.label, e, e2))
            sys.exit(1)
    r = estimate(samples)
    print("# clock_offset %s pc_wall=%.6f board_time=%.6f uptime=%.2f offset_board_minus_pc=%.6f uptime_minus_pc=%.6f rtt_ms=%.2f via=%s"
          % (a.label, r["pc_wall"], r["board_time"], r["uptime"], r["offset"], r["up_offset"], r["rtt_ms"], via))


if __name__ == "__main__":
    main()
