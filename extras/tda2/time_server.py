#!/usr/bin/python
# Runs on the TDA2 (Python 2.7): answers every received line with "<time.time()> <uptime>\n" for sub-ms clock-offset estimation. Usage: nohup python /tmp/time_server.py [5010] &
import socket, sys, time

port = int(sys.argv[1]) if len(sys.argv) > 1 else 5010
srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("", port))
srv.listen(4)
while True:
    conn, _ = srv.accept()
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    try:
        while True:
            req = conn.recv(64)
            if not req:
                break
            try:
                up = open("/proc/uptime").read().split()[0]
            except Exception:
                up = "-1"
            conn.sendall("%.6f %s\n" % (time.time(), up))
    except socket.error:
        pass
    finally:
        conn.close()
