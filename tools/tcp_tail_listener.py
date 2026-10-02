"""PC side of the stream: one TCP server per device re-framing the byte stream, the 16-RX frame mux, the recorder and the replay source."""
import argparse
import json
import os
import queue
import socket
import sys
import threading as th
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cfg  # noqa: E402

DEVICES = ("master", "slave1", "slave2", "slave3")
NUM_RX_PER_DEVICE = 4
CAPTURES = os.path.join(cfg.ROOT, "captures")


def frame_bytes_per_device(samples, chirps_per_loop, loops, rx=NUM_RX_PER_DEVICE):
    return samples * chirps_per_loop * loops * rx * 2 * 2


def device_frame_to_cube(frame_i16, samples, chirps_per_loop, loops, rx=NUM_RX_PER_DEVICE):
    x = np.asarray(frame_i16, dtype=np.int16)
    c = x[0::2].astype(np.float32) + 1j * x[1::2].astype(np.float32)
    return np.reshape(c, (rx, samples, chirps_per_loop, loops), order="F")


def to_matlab_layout(cube):
    return np.transpose(cube, (1, 3, 0, 2))


class TcpTailListener(th.Thread):
    def __init__(self, name, data_queue, frame_length, address, rcvbuf_bytes=64 << 20, emit_index=False, recv_chunk=4 << 20):
        super().__init__(name=name)
        self.data_queue = data_queue
        self.frame_bytes = int(frame_length) * 2
        self.address = address
        self.rcvbuf_bytes = rcvbuf_bytes
        self.emit_index = emit_index
        self.recv_chunk = recv_chunk
        self._running = True
        self.daemon = True
        self.sock = None
        self.conn = None
        self.stats = dict(bytes=0, frames=0, last_frame_time=None, connections=0, connected=False,
                          first_byte_time=None, dropped_queue=0, partial_at_close=0)

    def stop(self):
        self._running = False
        for s in (self.conn, self.sock):
            try:
                if s is not None:
                    s.close()
            except Exception:
                pass

    def _put(self, item):
        try:
            self.data_queue.put(item, block=False)
        except queue.Full:
            self.stats["dropped_queue"] += 1
            try:
                self.data_queue.get_nowait()
            except queue.Empty:
                pass
            self.data_queue.put(item, block=False)

    def _serve_connection(self, conn):
        fb = self.frame_bytes
        buf = bytearray()
        stream_off = 0
        rbuf = bytearray(self.recv_chunk)
        view = memoryview(rbuf)
        conn.settimeout(1.0)
        while self._running:
            try:
                n = conn.recv_into(view)
            except socket.timeout:
                continue
            except OSError:
                break
            if n == 0:
                break
            t_perf = time.perf_counter()
            if self.stats["first_byte_time"] is None:
                self.stats["first_byte_time"] = t_perf
            self.stats["bytes"] += n
            buf += view[:n]
            while len(buf) >= fb:
                frame = np.frombuffer(bytes(buf[:fb]), dtype="<i2")
                idx = stream_off // fb
                self._put((idx, frame) if self.emit_index else frame)
                self.stats["frames"] += 1
                self.stats["last_frame_time"] = t_perf
                del buf[:fb]
                stream_off += fb
        self.stats["partial_at_close"] = len(buf)

    def run(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.rcvbuf_bytes)
        try:
            self.sock.bind(self.address)
        except OSError as e:
            print("[listener %s] cannot bind %s: %s (another listener or viewer owns the port)" % (self.name, self.address, e), flush=True)
            self.stats["bind_error"] = str(e)
            self._running = False
            return
        self.sock.listen(1)
        self.sock.settimeout(1.0)
        print("[listener %s] listening on %s, frame_bytes=%d" % (self.name, self.address, self.frame_bytes), flush=True)
        try:
            while self._running:
                try:
                    conn, addr = self.sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                self.conn = conn
                self.stats["connections"] += 1
                self.stats["connected"] = True
                print("[listener %s] connection from %s" % (self.name, addr), flush=True)
                self._serve_connection(conn)
                self.stats["connected"] = False
                try:
                    conn.close()
                except Exception:
                    pass
                print("[listener %s] connection closed; stats=%s" % (self.name, self.stats), flush=True)
        finally:
            try:
                self.sock.close()
            except Exception:
                pass


class CascadeFrameMux(th.Thread):
    def __init__(self, queues, out_queue, samples, chirps_per_loop, loops, max_pending=64, max_age_s=0.25, name="mux", raw_sink=None):
        super().__init__(name=name)
        self.queues = queues
        self.out_queue = out_queue
        self.raw_sink = raw_sink
        self.samples, self.chirps, self.loops = samples, chirps_per_loop, loops
        self.max_pending = max_pending
        self.max_age_s = max_age_s
        self.pending = {}
        self.pending_t0 = {}
        self.last_emitted = -1
        self.stats = dict(emitted=0, stale=0, incomplete_dropped=0, gaps=0, last_idx=-1, restarts=0,
                          missing_by_dev={d: 0 for d in DEVICES})
        self._running = True
        self.daemon = True

    def stop(self):
        self._running = False

    def assemble(self, frames_by_dev):
        cubes = [device_frame_to_cube(frames_by_dev[d], self.samples, self.chirps, self.loops) for d in DEVICES]
        return np.concatenate(cubes, axis=0)

    def _drop(self, k):
        parts = self.pending.pop(k)
        self.pending_t0.pop(k, None)
        for d in DEVICES:
            if d not in parts:
                self.stats["missing_by_dev"][d] += 1
        self.stats["incomplete_dropped"] += 1

    def _emit(self, idx, cube):
        try:
            self.out_queue.put((idx, cube), block=False)
        except queue.Full:
            try:
                self.out_queue.get_nowait()
            except queue.Empty:
                pass
            self.out_queue.put((idx, cube), block=False)

    def _offer(self, dev, idx, frame):
        if idx <= self.last_emitted:
            new_capture = idx < self.last_emitted - 4 * self.max_pending and idx < 64
            if not new_capture:
                self.stats["stale"] += 1
                return
            self.pending.clear(); self.pending_t0.clear()
            self.last_emitted = -1
            self.stats["restarts"] += 1
        if idx not in self.pending:
            self.pending[idx] = {}
            self.pending_t0[idx] = time.perf_counter()
        self.pending[idx][dev] = frame
        if len(self.pending[idx]) == len(DEVICES):
            parts = self.pending.pop(idx)
            if self.raw_sink is not None:
                try:
                    self.raw_sink(idx, parts)
                except Exception as e:
                    self.stats["raw_sink_errors"] = self.stats.get("raw_sink_errors", 0) + 1
                    self.stats["raw_sink_last_error"] = str(e)[:120]
            cube = self.assemble(parts)
            self.pending_t0.pop(idx, None)
            if self.last_emitted >= 0 and idx != self.last_emitted + 1:
                self.stats["gaps"] += idx - self.last_emitted - 1
            for k in [k for k in self.pending if k < idx]:
                self._drop(k)
            self.last_emitted = idx
            self.stats["emitted"] += 1
            self.stats["last_idx"] = idx
            self._emit(idx, cube)
        while len(self.pending) > self.max_pending:
            self._drop(min(self.pending))

    def _expire(self):
        if not self.pending or self.max_age_s <= 0:
            return
        now = time.perf_counter()
        for k in sorted(self.pending):
            if now - self.pending_t0.get(k, now) > self.max_age_s:
                self._drop(k)
                if k > self.last_emitted:
                    self.last_emitted = k

    def run(self):
        while self._running:
            got = False
            for dev, q in self.queues.items():
                try:
                    idx, frame = q.get(timeout=0.005)
                except queue.Empty:
                    continue
                got = True
                self._offer(dev, idx, frame)
            self._expire()
            if not got:
                time.sleep(0.001)


class CaptureRecorder:
    def __init__(self, name, samples, chirps_per_loop, loops, period_ms=None, tag=None, root=CAPTURES, notes=""):
        self.dir = os.path.join(root, name)
        os.makedirs(self.dir, exist_ok=True)
        self.fb = frame_bytes_per_device(samples, chirps_per_loop, loops)
        self.config = dict(name=name, samples=samples, chirps=chirps_per_loop, loops=loops, frame_bytes_per_device=self.fb,
                           frame_bytes_total=4 * self.fb, devices=list(DEVICES), period_ms=period_ms, tag=tag,
                           start_wall=time.time(), start_iso=time.strftime("%Y-%m-%d %H:%M:%S"), notes=notes,
                           layout="per frame: master|slave1|slave2|slave3 raw int16 blocks, each as in <dev>_NNNN_data.bin")
        with open(os.path.join(self.dir, "config.json"), "w") as f:
            json.dump(self.config, f, indent=1)
        self.fbin = open(os.path.join(self.dir, "frames.bin"), "wb")
        self.fcsv = open(os.path.join(self.dir, "frames.csv"), "w")
        self.fcsv.write("frame_idx,t_pc_perf,t_pc_wall,byte_offset\n")
        self.n = 0
        self.offset = 0

    def on_set(self, idx, frames_by_dev):
        for d in DEVICES:
            self.fbin.write(np.ascontiguousarray(frames_by_dev[d], dtype="<i2").tobytes())
        self.fcsv.write("%d,%.6f,%.6f,%d\n" % (idx, time.perf_counter(), time.time(), self.offset))
        self.offset += 4 * self.fb
        self.n += 1
        if self.n % 10 == 0:
            self.fcsv.flush()
            self.fbin.flush()

    def close(self):
        self.fbin.close()
        self.fcsv.close()
        self.config.update(frames_recorded=self.n, bytes=self.offset, end_wall=time.time())
        with open(os.path.join(self.dir, "config.json"), "w") as f:
            json.dump(self.config, f, indent=1)


class ReplaySource(th.Thread):
    def __init__(self, name, queues, root=CAPTURES, speed=1.0, loop=False, start=0, count=0):
        super().__init__(name="replay")
        self.dir = os.path.join(root, name)
        self.config = json.load(open(os.path.join(self.dir, "config.json")))
        self.queues = queues
        self.speed, self.loop, self.first, self.count = speed, loop, start, count
        self.fb = self.config["frame_bytes_per_device"]
        rows = np.loadtxt(os.path.join(self.dir, "frames.csv"), delimiter=",", skiprows=1, ndmin=2)
        self.idx = rows[:, 0].astype(int)
        self.t_perf = rows[:, 1]
        self.offsets = rows[:, 3].astype(np.int64)
        self.daemon = True
        self._running = True
        self.stats = dict(frames=0, passes=0)

    def stop(self):
        self._running = False

    def run(self):
        n = len(self.idx)
        lo = self.first
        hi = min(n, lo + self.count) if self.count else n
        span = int(self.idx[hi - 1]) + 1 if hi > lo else 0
        while self._running:
            base = self.stats["passes"] * span
            with open(os.path.join(self.dir, "frames.bin"), "rb") as f:
                t0_rec = self.t_perf[lo]
                t0 = time.perf_counter()
                for i in range(lo, hi):
                    if not self._running:
                        break
                    if self.speed > 0:
                        target = t0 + (self.t_perf[i] - t0_rec) / self.speed
                        while time.perf_counter() < target:
                            time.sleep(0.0005)
                    f.seek(int(self.offsets[i]))
                    raw = f.read(4 * self.fb)
                    if len(raw) < 4 * self.fb:
                        break
                    for k, d in enumerate(DEVICES):
                        frame = np.frombuffer(raw[k * self.fb:(k + 1) * self.fb], dtype="<i2")
                        try:
                            self.queues[d].put((int(self.idx[i]) + base, frame), timeout=1.0)
                        except queue.Full:
                            pass
                    self.stats["frames"] += 1
            self.stats["passes"] += 1
            if not self.loop:
                break


def main():
    c = cfg.load()
    ap = argparse.ArgumentParser(description="headless listener: receives the four streams, muxes them and optionally records")
    ap.add_argument("--samples", type=int, default=c["capture"]["samples"])
    ap.add_argument("--chirps", type=int, default=c["capture"]["chirps"])
    ap.add_argument("--loops", type=int, default=c["capture"]["loops"])
    ap.add_argument("--period-ms", type=float, default=c["capture"]["period_ms"])
    ap.add_argument("--host", default=c["pc"]["bind"])
    ap.add_argument("--duration", type=float, default=0, help="seconds to run (0 = until Ctrl-C)")
    ap.add_argument("--record-capture", default=None, help="record the muxed 16-RX frames to captures/<name>/")
    a = ap.parse_args()
    fb = frame_bytes_per_device(a.samples, a.chirps, a.loops)
    queues, listeners = {}, {}
    for dev, port in zip(DEVICES, c["pc"]["ports"]):
        q = queue.Queue(maxsize=4096)
        queues[dev] = q
        lst = TcpTailListener(dev, q, fb // 2, (a.host, port), emit_index=True)
        lst.start()
        listeners[dev] = lst
    mux_out = queue.Queue(maxsize=256)
    rec = CaptureRecorder(a.record_capture, a.samples, a.chirps, a.loops, period_ms=a.period_ms) if a.record_capture else None
    mux = CascadeFrameMux(queues, mux_out, a.samples, a.chirps, a.loops, raw_sink=(rec.on_set if rec else None))
    mux.start()
    t0 = time.perf_counter()
    last_t, last_bytes = t0, {d: 0 for d in DEVICES}
    try:
        while True:
            try:
                while True:
                    mux_out.get(timeout=0.05)
            except queue.Empty:
                pass
            t = time.perf_counter()
            if t - last_t >= 1.0:
                parts = []
                for d in DEVICES:
                    b = listeners[d].stats["bytes"]
                    parts.append("%s:%6.2fMB/s f=%d" % (d, (b - last_bytes[d]) / (t - last_t) / 1e6, listeners[d].stats["frames"]))
                    last_bytes[d] = b
                print("[%7.1fs] %s || mux emitted=%d gaps=%d incomplete=%d" % (
                    t - t0, " | ".join(parts), mux.stats["emitted"], mux.stats["gaps"], mux.stats["incomplete_dropped"]), flush=True)
                last_t = t
            if a.duration and t - t0 >= a.duration:
                break
    except KeyboardInterrupt:
        pass
    finally:
        mux.stop()
        for lst in listeners.values():
            lst.stop()
        time.sleep(0.5)
        if rec:
            rec.close()
            print("recorded %d frames to %s" % (rec.n, rec.dir), flush=True)
        print("mux stats %s" % mux.stats, flush=True)


if __name__ == "__main__":
    main()
