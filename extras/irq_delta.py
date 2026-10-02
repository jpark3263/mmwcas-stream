"""Interrupt-counter and nERROR discriminator for one experiment run: per-IRQ deltas before/during/after the frame window (board irq.txt + gpio.txt + clock.txt + Studio's own log)."""
import argparse
import datetime as dt
import glob
import os
import re

KEY = ("mbox_ipu2_ipc3x", "nvme0q0", "nvme0q2", "dra7-pcie-msi", "48484000.ethernet", "l3-app-irq", "l3-dbg-irq", "omap-dma-engine", "edma_ccint")


def parse_irq_log(path):
    snaps = []
    cur_t = None; cur = {}
    for line in open(path):
        if line.startswith("###"):
            if cur_t is not None:
                snaps.append((cur_t, cur))
            parts = line.split()
            cur_t = float(parts[1]) if len(parts) > 1 and parts[1] != "end" else None
            cur = {}
            continue
        m = re.match(r"\s*(\S+):\s+(\d+)\s+(\d+)\s+(.*)$", line)
        if not m or cur_t is None:
            continue
        irq, c0, c1, rest = m.groups()
        name = rest.split()[-1] if rest.split() else irq
        if irq.startswith("IPI") or irq == "Err":
            name = irq + " " + " ".join(rest.split()[:2])
        else:
            name = "%s %s" % (irq, name if "PCI-MSI" not in rest else " ".join(rest.split()[-2:]).rstrip(","))
        cur[name] = int(c0) + int(c1)
    if cur_t is not None:
        snaps.append((cur_t, cur))
    return snaps


def newest_studio_log():
    files = glob.glob(os.path.join(os.environ.get("APPDATA", ""), "RSTD", "Output", "Log", "Log*_0.txt"))
    return max(files, key=os.path.getmtime) if files else None


def studio_times(path, cap_dir):
    lines = open(path, "rb").read().decode("latin-1").splitlines()
    start = None
    for i, l in enumerate(lines):
        if "TDACaptureCard_StartRecord_mult" in l and cap_dir in l:
            start = i
    if start is None:
        return None
    out = dict(arm=None, start_frames=[], frame_ends=[], stop_record=None, connect_tda=None, connect_ok=None, master_fw=None, slaves_fw=None, async_other=[])
    for l in lines[:start][::-1]:
        if "TDACaptureCard_StartRecord_mult" in l:
            break
        if "ar1.ConnectTDA(" in l and out["connect_tda"] is None: out["connect_tda"] = l[1:9]
        if "ConnectTDA Successful" in l and out["connect_ok"] is None: out["connect_ok"] = l[1:9]
        if "Master : FW Download Successful" in l and out["master_fw"] is None: out["master_fw"] = l[1:9]
        if "Slaves : FW Download Successful" in l and out["slaves_fw"] is None: out["slaves_fw"] = l[1:9]
        if "sync event" in l and "Frame start" not in l and "Frame End" not in l:
            out["async_other"].append(l.strip()[:160])
    for l in lines[start - 3:]:
        t = l[1:9]
        if "Starting TDA ARM" in l and out["arm"] is None: out["arm"] = t
        elif "Start Frame Successful" in l: out["start_frames"].append(t)
        elif "Frame End async event" in l or "Frame Ended" in l: out["frame_ends"].append(t)
        elif "TDACaptureCard_StopRecord_mult" in l and out["stop_record"] is None: out["stop_record"] = t
        elif "sync event" in l and "Frame start" not in l and "Frame End" not in l: out["async_other"].append(l.strip()[:160])
        elif "Capture sequence completed" in l: break
    return out


def parse_gpio_log(path):
    out = []
    for line in open(path):
        if not line.startswith("### "):
            continue
        parts = line.split()
        try:
            t = float(parts[1])
        except (IndexError, ValueError):
            continue
        d = [p for p in parts if p.startswith("din19=")]
        out.append((t, int(d[0][6:]) if d else None))
    return out


def at_or_before(series, t):
    best = None
    for s in series:
        if s[0] <= t:
            best = s
        else:
            break
    return best


def hms_to_uptime(hms, pc_epoch, uptime_minus_pc):
    day = dt.datetime.fromtimestamp(pc_epoch).date()
    h, m, s = [int(x) for x in hms.split(":")]
    return dt.datetime.combine(day, dt.time(h, m, s)).timestamp() + uptime_minus_pc


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_dir")
    ap.add_argument("--studio-log", default=None)
    a = ap.parse_args()
    run = a.run_dir
    irq_log = os.path.join(run, "irq.txt")
    if not os.path.exists(irq_log):
        print("-- irq: no %s" % irq_log); return
    snaps = parse_irq_log(irq_log)
    if len(snaps) < 2:
        print("-- irq: only %d snapshots" % len(snaps)); return
    cap_dir = os.path.basename(os.path.normpath(run))
    clk = open(os.path.join(run, "clock.txt")).read() if os.path.exists(os.path.join(run, "clock.txt")) else ""
    m = list(re.finditer(r"# clock_offset before pc_wall=([\d.]+) .*?uptime=([\d.]+) .*?uptime_minus_pc=([-\d.]+)", clk))
    if not m:
        print("-- irq: no clock offset in clock.txt"); return
    pc_epoch, ump = float(m[-1].group(1)), float(m[-1].group(3))
    slog = a.studio_log or newest_studio_log()
    st = studio_times(slog, cap_dir) if slog else None
    print("-- IRQ discriminator (%d snapshots, %.1f..%.1f s uptime, studio log %s)" % (len(snaps), snaps[0][0], snaps[-1][0], os.path.basename(slog or "-")))
    if not st or not st["arm"]:
        print("   run %s not found in the Studio log; whole-run deltas only" % cap_dir)
        t_arm = t_sf = snaps[0][0]; t_fe = snaps[-1][0]
    else:
        t_arm = hms_to_uptime(st["arm"], pc_epoch, ump)
        t_sf = hms_to_uptime(st["start_frames"][0], pc_epoch, ump) if st["start_frames"] else t_arm + 1
        t_fe = hms_to_uptime(st["frame_ends"][-1], pc_epoch, ump) + 1 if st["frame_ends"] else (hms_to_uptime(st["stop_record"], pc_epoch, ump) if st["stop_record"] else snaps[-1][0])
        print("   ARM %s -> uptime %.1f | first Start Frame %s -> %.1f | %d Frame End events, last %s -> %.1f | StopRecord %s"
              % (st["arm"], t_arm, st["start_frames"][0] if st["start_frames"] else "-", t_sf, len(st["frame_ends"]), st["frame_ends"][-1] if st["frame_ends"] else "-", t_fe, st["stop_record"]))
    windows = [("baseline 5 s", t_arm - 5, t_arm), ("arm->start", t_arm, t_sf), ("FRAMES", t_sf, t_fe), ("after 3 s", t_fe, t_fe + 3)]
    names = sorted(set(k for _, c in snaps for k in c))
    rows = []
    for name in names:
        d = []
        for _, t0, t1 in windows:
            c0 = (at_or_before(snaps, t0) or snaps[0])[1].get(name, 0); c1 = (at_or_before(snaps, t1) or snaps[0])[1].get(name, 0)
            d.append(c1 - c0)
        if any(d) or any(k in name for k in KEY):
            rows.append((name, d))
    print("   %-34s %12s %12s %12s %12s" % ("irq", "baseline", "arm->start", "FRAMES", "after"))
    for name, d in rows:
        print("   %-34s %12d %12d %12d %12d%s" % (name, d[0], d[1], d[2], d[3], " <==" if any(k in name for k in ("mbox_ipu2", "nvme")) else ""))
    mb = [d for name, d in rows if "mbox_ipu2" in name]
    nv = [d for name, d in rows if "nvme" in name]
    print("   VERDICT: mbox_ipu2 (IPU2->A15) during the frame window: %+d (baseline %+d); nvme: %+d (baseline %+d)"
          % (mb[0][2] if mb else 0, mb[0][0] if mb else 0, sum(d[2] for d in nv), sum(d[0] for d in nv)))
    gp = os.path.join(run, "gpio.txt")
    if os.path.exists(gp):
        g = parse_gpio_log(gp)
        vals = [v for _, v in g if v is not None]
        if g and vals:
            def show(label, hms, extra=0.0):
                if not hms:
                    print("   nERROR %-28s : (no timestamp)" % label); return
                s = at_or_before(g, hms_to_uptime(hms, pc_epoch, ump) + extra)
                print("   nERROR %-28s : %s  (sample at uptime %.2f)" % (label, ("LOW/asserted" if s[1] == 0 else "HIGH") if s and s[1] is not None else "n/a", s[0] if s else -1))
            print("   nERROR (TDA_GPIO2_19; 0 = LOW = asserted): %d samples, LOW in %d, HIGH in %d, first %s, last %s"
                  % (len(vals), vals.count(0), vals.count(1), "LOW" if vals[0] == 0 else "HIGH", "LOW" if vals[-1] == 0 else "HIGH"))
            if st:
                show("after ConnectTDA", st.get("connect_ok"), 0.5)
                show("after master FW download", st.get("master_fw"), 0.5)
                show("after slave FW download", st.get("slaves_fw"), 0.5)
                show("at ARM", st.get("arm"), 0.5)
                show("frame window (mid)", st["start_frames"][0] if st["start_frames"] else None, 0.6)
                show("after Stop (+2 s)", st.get("stop_record"), 2.0)
            edges = [(g[i][0], g[i][1]) for i in range(1, len(g)) if g[i][1] != g[i - 1][1] and g[i][1] is not None]
            print("   nERROR transitions (uptime -> new value): %s" % (", ".join("%.2f->%s" % (t, "LOW" if v == 0 else "HIGH") for t, v in edges[:20]) or "none"))
    if st and st.get("async_other"):
        print("   other async events from the devices in this run: %d" % len(st["async_other"]))
        for l in st["async_other"][:12]:
            print("      " + l)
    print("   time series (dt=0.25 s) uptime : d(mbox_ipu2) d(nvme total)   [S = Start Frame, E = last Frame End]")
    prev = None
    for t, c in snaps:
        if t < t_sf - 1.5 or t > t_fe + 1.5:
            prev = (t, c); continue
        if prev is not None:
            dm = sum(v for k, v in c.items() if "mbox_ipu2" in k) - sum(v for k, v in prev[1].items() if "mbox_ipu2" in k)
            dn = sum(v for k, v in c.items() if "nvme" in k) - sum(v for k, v in prev[1].items() if "nvme" in k)
            tagc = "S" if prev[0] < t_sf <= t else ("E" if prev[0] < t_fe <= t else " ")
            print("     %s %9.2f : %5d %5d" % (tagc, t, dm, dn))
        prev = (t, c)


if __name__ == "__main__":
    main()
