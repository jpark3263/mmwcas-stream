"""Reads a TDA2 capture index file (<dev>_NNNN_idx.bin: 24-byte 'bckt' header, 48-byte records with frame size, timestamp and offset)."""
import argparse
import os
import struct

import numpy as np

HDR = struct.Struct("<4sIIIQ")
REC_DTYPE = np.dtype([("tag", "S2"), ("version", "<u2"), ("flags", "<u4"), ("width", "<u2"), ("height", "<u2"), ("pitch", "<u4"),
                      ("meta0", "<u4"), ("meta1", "<u4"), ("meta2", "<u4"), ("frame_bytes", "<u4"), ("timestamp_us", "<u8"), ("offset", "<u8")])


def parse_idx(path_or_bytes):
    raw = bytes(path_or_bytes) if isinstance(path_or_bytes, (bytes, bytearray)) else open(path_or_bytes, "rb").read()
    if len(raw) < HDR.size:
        raise ValueError("idx file shorter than its header (%d bytes)" % len(raw))
    tag, version, flags, num_idx, data_size = HDR.unpack_from(raw, 0)
    if tag != b"bckt":
        raise ValueError("bad header tag %r" % tag)
    n = (len(raw) - HDR.size) // REC_DTYPE.itemsize
    recs = np.frombuffer(raw, dtype=REC_DTYPE, count=n, offset=HDR.size)
    return dict(version=version, flags=flags, num_idx=num_idx, data_size=data_size, num_records_in_file=n), recs


def summarize(hdr, recs, name=""):
    lines = ["== %s" % name, "  header: %s" % hdr]
    if len(recs) == 0:
        lines.append("  (no records)")
        return "\n".join(lines)
    ts = recs["timestamp_us"].astype(np.int64)
    off = recs["offset"].astype(np.int64)
    fb = int(recs["frame_bytes"][0])
    lines.append("  records: %d   width=%d height=%d pitch=%d frame_bytes=%d" % (len(recs), recs["width"][0], recs["height"][0], recs["pitch"][0], fb))
    if len(recs) > 1:
        dts = np.diff(ts)
        lines.append("  timestamp: first=%d us last=%d us; dt median=%.1f us min=%d max=%d" % (ts[0], ts[-1], float(np.median(dts)), dts.min(), dts.max()))
        lines.append("  offset step: unique=%s (expected %d)" % (np.unique(np.diff(off)).tolist(), fb))
        med = float(np.median(dts))
        gaps = np.where(dts > 1.5 * med)[0]
        lines.append("  timestamp gaps >1.5x median: %d %s" % (len(gaps), dts[gaps][:10].tolist() if len(gaps) else ""))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--csv", default=None, help="write the records of the first file as CSV")
    a = ap.parse_args()
    for i, p in enumerate(a.files):
        hdr, recs = parse_idx(p)
        print(summarize(hdr, recs, os.path.basename(p)))
        if a.csv and i == 0:
            with open(a.csv, "w") as f:
                f.write("frame,timestamp_us,offset,frame_bytes\n")
                for k, r in enumerate(recs):
                    f.write("%d,%d,%d,%d\n" % (k, r["timestamp_us"], r["offset"], r["frame_bytes"]))
            print("wrote", a.csv)


if __name__ == "__main__":
    main()
