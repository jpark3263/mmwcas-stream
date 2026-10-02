#!/usr/bin/python
# Runs on the TDA2 (Python 2.7): streams one device's preallocated capture file to the PC, one complete frame slot at a time.
import os, re, sys, time, socket

PEEK = 4096
FILE_RE = re.compile(r"^(.*_)(\d{4})(_data\.bin)$")
_ZEROS = {}


def zeros(n):
    if n not in _ZEROS:
        _ZEROS[n] = b"\0" * n
    return _ZEROS[n]


def next_file(fn):
    m = FILE_RE.match(fn)
    return "%s%04d%s" % (m.group(1), int(m.group(2)) + 1, m.group(3)) if m else None


def next_file_ready(fn, fb):
    nxt = next_file(fn)
    if not nxt or not os.path.exists(nxt):
        return None
    try:
        if os.path.getsize(nxt) < fb:
            return None
        f = open(nxt, "rb", 0)
        try:
            f.seek(fb - PEEK)
            tail = f.read(PEEK)
        finally:
            f.close()
    except (IOError, OSError):
        return None
    return nxt if (len(tail) == PEEK and tail != zeros(PEEK)) else None


def hollow(buf, n):
    return n > 0 and zeros(n) in buf


def parse_args(argv):
    if len(argv) < 3:
        sys.stderr.write("usage: follow_slot.py DATA_FILE PC_IP PORT --frame-bytes N [--poll S] [--log FILE] [--wait-file] [--idle-exit S]\n")
        sys.exit(2)
    opt = dict(fn=argv[0], pc=argv[1], port=int(argv[2]), fb=0, poll=0.002, log=None, wait_file=False, idle_exit=0.0,
               read_timeout=2.0, zero_check=4096)
    i = 3
    while i < len(argv):
        a = argv[i]
        if a == "--frame-bytes": opt["fb"] = int(argv[i + 1]); i += 2
        elif a == "--poll": opt["poll"] = float(argv[i + 1]); i += 2
        elif a == "--log": opt["log"] = argv[i + 1]; i += 2
        elif a == "--wait-file": opt["wait_file"] = True; i += 1
        elif a == "--idle-exit": opt["idle_exit"] = float(argv[i + 1]); i += 2
        elif a == "--read-timeout": opt["read_timeout"] = float(argv[i + 1]); i += 2
        elif a == "--zero-check": opt["zero_check"] = int(argv[i + 1]); i += 2
        else: sys.stderr.write("unknown arg %s\n" % a); sys.exit(2)
    if opt["fb"] <= 0:
        sys.stderr.write("--frame-bytes is required\n"); sys.exit(2)
    return opt


def main():
    o = parse_args(sys.argv[1:])
    fn, fb, poll = o["fn"], o["fb"], o["poll"]
    if o["wait_file"]:
        while not os.path.exists(fn):
            time.sleep(0.05)
    lf = open(o["log"], "wb", 0) if o["log"] else None

    def w(s):
        if lf: lf.write(s.encode("ascii"))

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 << 20)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    s.connect((o["pc"], o["port"]))
    fd = open(fn, "rb", 0)
    k = k_base = 0
    sent = nsent = nzero = nretry = nroll = 0
    t_last = time.time()
    w("# follow_slot %s -> %s:%d frame_bytes=%d start=%.6f poll=%.4f zero_check=%d\n"
      % (fn, o["pc"], o["port"], fb, t_last, poll, o["zero_check"]))

    def rollover(nxt, size):
        fd.close()
        w("# ROLLOVER to %s at frame %d (previous file %d B, %d frames)\n" % (nxt, k, size, k - k_base))
        return open(nxt, "rb", 0)

    try:
        while True:
            off = (k - k_base) * fb
            try:
                size = os.fstat(fd.fileno()).st_size
            except OSError:
                size = 0
            if off + fb > size:
                nxt = next_file(fn)
                if nxt and os.path.exists(nxt) and os.path.getsize(nxt) >= fb:
                    fd = rollover(nxt, size); fn = nxt; k_base = k; nroll += 1
                    continue
                if o["idle_exit"] and time.time() - t_last > o["idle_exit"]:
                    break
                time.sleep(poll)
                continue
            fd.seek(off + fb - PEEK)
            tail = fd.read(PEEK)
            if len(tail) < PEEK or tail == zeros(PEEK):
                if k > k_base:
                    nxt = next_file_ready(fn, fb)
                    if nxt:
                        fd = rollover(nxt, size); fn = nxt; k_base = k; nroll += 1
                        continue
                if o["idle_exit"] and time.time() - t_last > o["idle_exit"]:
                    break
                time.sleep(poll)
                continue
            t_seen = time.time()
            fd.seek(off)
            buf = fd.read(fb)
            t_dead = t_seen + o["read_timeout"]
            retried = 0
            while time.time() < t_dead and (len(buf) < fb or hollow(buf, o["zero_check"])):
                time.sleep(poll); retried += 1
                fd.seek(off)
                buf = fd.read(fb)
            if len(buf) < fb:
                w("# SHORT slot %d got=%d (waiting)\n" % (k, len(buf)))
                time.sleep(poll)
                continue
            if retried:
                nretry += 1
            flag = ""
            if hollow(buf, o["zero_check"]):
                nzero += 1; flag = " ZERO"
            s.sendall(buf)
            sent += fb; nsent += 1
            t = time.time()
            w("%.6f %d %d %d %.6f %d%s\n" % (t, sent, fb, k, t_seen, retried, flag))
            t_last = t
            k += 1
    except socket.error as e:
        sys.stderr.write("socket error: %s\n" % e)
    finally:
        w("# end sent=%d frames=%d next_frame=%d zero=%d retried=%d rollovers=%d t=%.6f\n" % (sent, nsent, k, nzero, nretry, nroll, time.time()))
        if lf: lf.close()
        try: s.close()
        except Exception: pass


if __name__ == "__main__":
    main()
