"""Estimates (Vision SDK global timer) - (Linux uptime) on the board from apps.out's console timestamps in the journal, prints one '# vsdk_timer_offset' line."""
import argparse
import os
import re
import subprocess

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SSH = ["sh", os.path.join(ROOT, "tools", "tda2_ssh.sh")]
PAT = re.compile(r"^\[\s*([0-9]+\.[0-9]+)\].*?([0-9]+\.[0-9]{6}) s:")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--label", default="")
    ap.add_argument("--lines", type=int, default=400)
    a = ap.parse_args()
    r = subprocess.run(SSH + ["journalctl -n %d --no-pager -o short-monotonic 2>/dev/null | grep ' s:'" % a.lines], capture_output=True, text=True, timeout=30)
    diffs = sorted(float(m.group(2)) - float(m.group(1)) for m in (PAT.match(l) for l in r.stdout.splitlines()) if m)
    if not diffs:
        print("# vsdk_timer_offset %s ERROR no matching journal lines (stderr=%r)" % (a.label, r.stderr[:200]))
        return
    print("# vsdk_timer_offset %s n=%d vsdk_minus_uptime_s=%.6f median=%.6f min=%.6f max=%.6f"
          % (a.label, len(diffs), diffs[-1], diffs[len(diffs) // 2], diffs[0], diffs[-1]))


if __name__ == "__main__":
    main()
