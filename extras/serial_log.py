"""Read-only serial console logger: python extras/serial_log.py COM7 logs/serial.txt [115200]; stop by creating <log>.stop."""
import os
import sys
import time

import serial

port, log = sys.argv[1], sys.argv[2]
baud = int(sys.argv[3]) if len(sys.argv) > 3 else 115200
stop = log + ".stop"
os.makedirs(os.path.dirname(os.path.abspath(log)), exist_ok=True)
f = open(log, "a", buffering=1, encoding="utf-8", errors="replace")
try:
    s = serial.Serial(port, baud, bytesize=8, parity="N", stopbits=1, timeout=0.5, rtscts=False, dsrdtr=False)
except Exception as e:
    f.write("%s # OPEN FAILED %s %d 8N1: %s\n" % (time.strftime("%H:%M:%S"), port, baud, e)); f.close(); sys.exit(1)
f.write("%s # opened %s %d 8N1 read-only, pid %d\n" % (time.strftime("%H:%M:%S"), port, baud, os.getpid()))
buf = b""
try:
    while not os.path.exists(stop):
        data = s.read(4096)
        if data:
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                f.write("%s %s\n" % (time.strftime("%H:%M:%S"), line.decode("latin-1").rstrip("\r")))
        elif buf and (buf.endswith(b": ") or buf.endswith(b"login: ") or buf.endswith(b"# ")):
            f.write("%s %s\n" % (time.strftime("%H:%M:%S"), buf.decode("latin-1")))
            buf = b""
finally:
    f.write("%s # closed (%s)\n" % (time.strftime("%H:%M:%S"), "stop file" if os.path.exists(stop) else "exit"))
    f.close(); s.close()
