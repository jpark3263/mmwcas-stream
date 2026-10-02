"""Summarizes an extras/soak.sh run directory (logs/soak_<ts>/): cycle table, TDA loss from the idx files, PC delivery, latencies, monitor rows, anomalies."""
import datetime
import glob
import json
import os
import re
import sys

import numpy as np

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from parse_idx import parse_idx  # noqa: E402

DEVICES = ("master", "slave1", "slave2", "slave3")


def rows_of(path):
    return [l.rstrip("\n") for l in open(path, errors="replace")] if os.path.exists(path) else []


def pct(x, p):
    return float(np.percentile(x, p)) if len(x) else float("nan")


def parse_soaklog(path):
    lines = rows_of(path)
    cycles = []
    windows = {}
    attempt = 0
    batch = None
    for l in lines:
        m = re.search(r"^(\d\d:\d\d:\d\d) == stage 1: .*attempt (\d+)", l)
        if m:
            attempt = int(m.group(2)); batch = None
            windows.setdefault(1, [m.group(1), None])
            continue
        if l.startswith("== soak cycles:"):
            batch = "A" if batch is None else "B"
            continue
        if l.startswith("cycle ") or l.startswith("!! CYCLE"):
            cycles.append((attempt, batch or "?", l))
            continue
        m = re.search(r"^(\d\d:\d\d:\d\d) == stage ([23]):", l)
        if m:
            windows[int(m.group(2))] = [m.group(1), None]
            continue
        m = re.search(r"^(\d\d:\d\d:\d\d) -- stage ([23]) done", l)
        if m and int(m.group(2)) in windows:
            windows[int(m.group(2))][1] = m.group(1)
    if 1 in windows:
        w2 = windows.get(2)
        windows[1][1] = w2[0] if w2 else None
    return dict(cycles=cycles, windows=windows, bangs=[l for l in lines if "!!" in l])


def cycle_fields(line):
    if not line.startswith("cycle "):
        return None
    p = [x.strip() for x in line.split("|")]
    d = dict(no=int(p[0].split()[1]), start=p[1], timing=p[2], dur=p[3], stop=p[4].replace("stop=", ""), raw=line)
    m = re.search(r"StopFrame (\d)/4, verified (\d)/4, stream.sh verified-line (\d)", p[5])
    d["stopped"], d["verified"], d["ended"] = (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (-1, -1, -1)
    m = re.search(r"PC frames (\d+)", p[6]); d["pc"] = int(m.group(1)) if m else -1
    m = re.search(r"TDA: (\d+) fr, dt ([\d.]+) ms, max gap ([\d.]+) ms", p[7])
    d["tda"], d["dt"], d["maxgap"] = (int(m.group(1)), float(m.group(2)), float(m.group(3))) if m else (-1, float("nan"), float("nan"))
    d["clean"] = "ports 0 board 0 locks 0" in line
    d["passed"] = d["stopped"] == 4 and d["verified"] == 4 and d["ended"] == 1 and d["clean"]
    return d


def read_follower(path):
    if not os.path.exists(path):
        return None, [], None
    hdr = [l for l in rows_of(path) if l.startswith("#")]
    roll = [l for l in hdr if "ROLLOVER" in l]
    end = [l for l in hdr if l.startswith("# end")]
    try:
        f = np.loadtxt(path, comments="#", ndmin=2)
    except Exception:
        f = None
    return f, roll, (end[-1] if end else None)


def read_arrivals(path):
    if not os.path.exists(path):
        return None
    try:
        a = np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2)
    except Exception:
        return None
    return a if len(a) and a.shape[1] >= 2 else None


def load_idx(idx_dir, dev):
    files = sorted(glob.glob(os.path.join(idx_dir, "%s_*_idx.bin" % dev)))
    ts = [parse_idx(f)[1]["timestamp_us"].astype(np.int64) / 1e6 for f in files]
    return (np.concatenate(ts) if ts else np.zeros(0)), len(files)


def gap_stats(t, period):
    g = np.diff(t)
    big = g[g > 1.75 * period]
    n_lost_gaps = int(np.sum(np.round(big / period) - 1)) if len(big) else 0
    expected = int(round((t[-1] - t[0]) / period)) + 1 if len(t) > 1 else len(t)
    small = int(np.sum((big >= 1.75 * period) & (big < 5 * period)))
    return dict(n=len(t), span=float(t[-1] - t[0]) if len(t) > 1 else 0.0, expected=expected, lost=expected - len(t), lost_gapsum=n_lost_gaps,
                stalls=int(len(big)), stalls_small=small, stalls_big=int(len(big)) - small, longest_ms=float(g.max() * 1e3) if len(g) else 0.0, gaps=g)


def anchored(raw, t_wall):
    tm = ((t_wall - t_wall[0]) // 60).astype(int)
    out = np.empty_like(raw)
    for m in np.unique(tm):
        sel = tm == m
        out[sel] = raw[sel] - np.percentile(raw[sel], 0.5)
    return out


def stage_report(sd, title, window, date):
    print("\n-- %s" % title)
    if not os.path.isdir(sd):
        print("   not run"); return {}
    res = {}
    capdir = (rows_of(os.path.join(sd, "capture_dir.txt")) or [""])[0].strip()
    f, roll, fend = read_follower(os.path.join(sd, "follow_master.log"))
    a = read_arrivals(os.path.join(sd, "arrivals.csv"))
    period = 0.02
    if a is not None and len(a) > 100:
        period = round(float(np.median(np.diff(a[:, 1]))), 3)
    print("   capture dir %s | period %.0f ms" % (capdir, period * 1e3))
    ts = None
    idx_dir = os.path.join(sd, "idx")
    if glob.glob(os.path.join(idx_dir, "master_*_idx.bin")):
        counts = {}
        for d in DEVICES:
            t_d, nf = load_idx(idx_dir, d)
            counts[d] = (len(t_d), nf)
            if d == "master":
                ts, n_files = t_d, nf
        if ts is not None and len(ts) > 1:
            gs = gap_stats(ts, period)
            res.update(tda_frames=gs["n"], tda_lost=gs["lost"], tda_longest_ms=gs["longest_ms"], tda_stalls=gs["stalls"])
            print("   TDA (idx, %d file(s) per device): %d frames captured of %d generated in %.1f s -> LOST %d (%.2f %%); gap sum says %d; "
                  "timestamp gaps >35 ms: %d (%d of 1-4 frames, %d longer); longest gap %.0f ms"
                  % (n_files, gs["n"], gs["expected"], gs["span"], gs["lost"], 100.0 * gs["lost"] / max(gs["expected"], 1), gs["lost_gapsum"],
                     gs["stalls"], gs["stalls_small"], gs["stalls_big"], gs["longest_ms"]))
            if len(set(c[0] for c in counts.values())) > 1:
                print("   !! device frame counts differ: %s" % counts)
            tm = (ts - ts[0]) / 60.0
            g = gs["gaps"]
            prof = []
            for m in range(int(tm[-1]) + 1):
                sel = (tm[:-1] >= m) & (tm[:-1] < m + 1)
                gg = g[sel]; big = gg[gg > 1.75 * period]
                prof.append("%d:%d" % (m, int(np.sum(np.round(big / period) - 1)) if len(big) else 0))
            print("   TDA lost per minute: " + " ".join(prof))
    if ts is None:
        print("   TDA idx: not available for this stage")
        if f is not None and len(f) > 1:
            gs = gap_stats(f[:, 4], period)
            n_slots = int(f[-1, 3]) + 1
            expected = int(round((f[-1, 4] - f[0, 4]) / period)) + 1
            res.update(tda_frames=n_slots, tda_lost=expected - n_slots, tda_estimated=True)
            print("   TDA (estimate from the follower log): %d slots captured of ~%d generated in %.1f s -> LOST ~%d (%.2f %%); board flush stalls >100 ms: %d, longest %.0f ms"
                  % (n_slots, expected, f[-1, 4] - f[0, 4], expected - n_slots, 100.0 * (expected - n_slots) / expected, int(np.sum(gs["gaps"] > 0.1)), gs["longest_ms"]))
    if f is not None:
        at = [re.search(r"at frame (\d+)", l) for l in roll]
        print("   follower: %d slots sent, %d rollover(s)%s; %s" % (len(f), len(roll), (" at frames " + ", ".join(m.group(1) for m in at if m)) if roll else "",
                                                                   fend[:100] if fend else "no end line (killed at stop, normal)"))
    if a is not None and len(a) > 1:
        idx = a[:, 0].astype(int)
        missing = sorted(set(range(int(idx.min()), int(idx.max()) + 1)) - set(idx.tolist()))
        captured = res.get("tda_frames", int(idx.max()) + 1)
        ga = np.diff(a[:, 1])
        res.update(pc_frames=len(a), mux_dropped=len(missing), pc_longest_ms=float(ga.max() * 1e3))
        print("   PC (mux out): %d of %d captured frames delivered (%d incomplete 16-RX set(s) dropped%s); arrival gaps >100 ms: %d (burst deliveries, not loss), longest %.0f ms at frame %d (t=%.1f min)"
              % (len(a), captured, len(missing), (": idx " + ",".join(map(str, missing[:5]))) if missing else "", int(np.sum(ga > 0.1)), ga.max() * 1e3,
                 idx[int(np.argmax(ga))], (a[int(np.argmax(ga)), 1] - a[0, 1]) / 60))
        if f is not None and len(f) > 1:
            ok = (idx[1:] < len(f)) & (idx[:-1] < len(f))
            dseen = f[idx[1:][ok], 4] - f[idx[:-1][ok], 4]
            big = ga[ok] > 0.1
            print("   arrival gaps >100 ms: %d coincide with a board flush stall, %d are PC/network side" % (int(np.sum(big & (dseen > 0.1))), int(np.sum(big & (dseen <= 0.1)))))
            ok = idx < len(f)
            lat = anchored(a[ok, 1] - f[idx[ok], 0], a[ok, 1])
            res.update(lat_bp=(float(np.median(lat) * 1e3), pct(lat, 90) * 1e3, pct(lat, 99) * 1e3, float(lat.max() * 1e3)))
            print("   latency board->PC (follower send -> mux out, above the fastest frame of each minute) ms: med %.1f p90 %.1f p99 %.1f max %.0f" % res["lat_bp"])
            if ts is not None and len(ts) >= len(f):
                e2e = anchored(a[ok, 1] - ts[idx[ok]], a[ok, 1])
                bl = anchored(f[:, 0] - ts[:len(f)], f[:, 0])
                res.update(e2e=(float(np.median(e2e) * 1e3), pct(e2e, 90) * 1e3, pct(e2e, 99) * 1e3, float(e2e.max() * 1e3)))
                print("   latency e2e (capture -> mux out, above the fastest frame of each minute) ms: med %.1f p90 %.1f p99 %.1f max %.0f | board capture -> follower send: med %.1f p90 %.1f max %.0f"
                      % (res["e2e"] + (np.median(bl) * 1e3, pct(bl, 90) * 1e3, bl.max() * 1e3)))
    cfgp = os.path.join(sd, "config.json")
    if os.path.exists(cfgp):
        c = json.load(open(cfgp))
        n_csv = max(0, len(rows_of(os.path.join(sd, "frames.csv"))) - 1)
        print("   recording %s: frames_recorded %s (= delivered? %s), bytes %s, csv rows %d, period %s ms"
              % (c.get("name"), c.get("frames_recorded"), "yes" if c.get("frames_recorded") == res.get("pc_frames") else "NO", c.get("bytes"), n_csv, c.get("period_ms")))
    csvs = sorted(glob.glob(os.path.join(sd, "soak_monitor_*.csv")))
    if window and window[0] and date:
        t0 = datetime.datetime.strptime(date + window[0], "%Y%m%d%H:%M:%S") - datetime.timedelta(seconds=90)
        t1 = datetime.datetime.strptime(date + window[1], "%Y%m%d%H:%M:%S") if window[1] else None
        sel = []
        for c in csvs:
            m = re.search(r"_(\d{8}_\d{6})\.csv$", c)
            if not m:
                continue
            tc = datetime.datetime.strptime(m.group(1), "%Y%m%d_%H%M%S")
            if tc >= t0 and (t1 is None or tc <= t1):
                sel.append(c)
        csvs = sel or csvs[-1:]
    else:
        csvs = csvs[-1:]
    for c in csvs:
        r = rows_of(c)
        if len(r) < 2:
            continue
        hdr = r[0].split(",")
        print("   monitor %s: min | frames | arr.gaps | longest ms | mux drops | pipe ms | PC CPU%% | PC RAM%% | viewer MB | board MemAvailable MB | SSD free GB | rollovers" % os.path.basename(c))
        for l in r[1:]:
            p = l.split(",")
            if len(p) != len(hdr):
                continue
            m = dict(zip(hdr, p))
            print("     %5s | %5s | %4s | %6s | %4s | %5s | %4s | %4s | %5s | %6s | %6s | %s" % (
                m["t_min"], m["pc_frames"], m["stalls"], m["longest_gap_ms"], m["mux_drops"], m["pipeline_ms"], m["pc_cpu_pct"], m["pc_ram_pct"],
                m["viewer_rss_mb"], m["board_avail_mb"], m["ssd_free_gb"], m["rollovers"]))
    return res


def main():
    d = sys.argv[1]
    m = re.search(r"soak_(\d{8})_\d{6}", d)
    date = m.group(1) if m else None
    log = parse_soaklog(os.path.join(d, "soak.log"))
    print("=" * 100)
    print("SOAK SUMMARY  %s" % d)
    print("=" * 100)
    print("\n-- stage 1: start/stop cycles (attempt.batch+cycle)")
    print("   %-6s | %-8s | %-22s | %-11s | %-9s | %-8s | %-17s | %-8s | %s" % ("cycle", "start", "STREAMING / LIVE", "stop", "StopFrame", "verified", "PC = TDA frames", "max gap", "result"))
    npass = nfail = 0
    anomalies = []
    for attempt, batch, line in log["cycles"]:
        c = cycle_fields(line)
        if c is None:
            nfail += 1
            print("   %s" % line[:200])
            continue
        label = "%d.%s%d" % (attempt, batch, c["no"])
        flags = []
        if c["passed"]:
            npass += 1
        if c["pc"] != c["tda"]:
            flags.append("PC!=TDA")
        if c["maxgap"] > 250:
            flags.append("gap>250ms")
        if c["stopped"] == 0 and c["verified"] == 4:
            flags.append("radar was already stopped when our stop ran")
        res = ("PASS" if c["passed"] else "FAIL") + ((" (" + "; ".join(flags) + ")") if flags else "")
        print("   %-6s | %-8s | %-22s | %-11s | %-9s | %-8s | %-17s | %6.0f ms | %s" % (
            label, c["start"], c["timing"], c["stop"], "%d/4" % c["stopped"], "%d/4" % c["verified"], "%d = %d" % (c["pc"], c["tda"]), c["maxgap"], res))
        if not c["passed"] or flags:
            anomalies.append("cycle %s: %s" % (label, res))
    print("   => %d cycle(s) passed all checks, %d failure line(s)" % (npass, nfail))
    w = log["windows"]
    r2 = stage_report(os.path.join(d, "stream30"), "stage 2: 30-minute stream (viewer, no recording)", w.get(2), date)
    r3 = stage_report(os.path.join(d, "record10"), "stage 3: 10-minute stream with recording", w.get(3), date)
    print("\n-- TDA loss and latency, stage 2 vs stage 3")
    for name, r in (("30 min, no recording", r2), ("10 min, recording", r3)):
        if not r:
            continue
        total = r.get("tda_frames", 0) + r.get("tda_lost", 0)
        print("   %-22s TDA lost %s of %s (%.2f %%)%s | delivered %s, mux dropped %s | e2e med/p90/p99/max %s ms | board->PC med %s ms | longest arrival gap %.0f ms" % (
            name, r.get("tda_lost", "?"), total, 100.0 * r.get("tda_lost", 0) / max(total, 1), " (estimate)" if r.get("tda_estimated") else "",
            r.get("pc_frames", "?"), r.get("mux_dropped", "?"), ("%.0f/%.0f/%.0f/%.0f" % r["e2e"]) if "e2e" in r else "n/a (no idx)",
            ("%.1f" % r["lat_bp"][0]) if "lat_bp" in r else "?", r.get("pc_longest_ms", 0)))
    print("\n-- anomalies (soak.log '!!' lines + table flags)")
    for l in log["bangs"][:30] + anomalies:
        print("   " + l[:220])
    if not log["bangs"] and not anomalies:
        print("   none")
    print()


if __name__ == "__main__":
    main()
