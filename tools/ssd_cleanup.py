"""Deletes this tool's own capture directories (mmwcas_*) from the board's SSD once their idx files are archived under logs/runs/; KEEP_ names are never deleted."""
import argparse
import glob
import hashlib
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cfg  # noqa: E402

SSH = ["sh", os.path.join(cfg.ROOT, "tools", "tda2_ssh.sh")]
NAME_RE = re.compile(r"^mmwcas_(.*)$")
SSD = cfg.get("tda.ssd")


def ssh(cmd):
    return subprocess.run(SSH + [cmd], capture_output=True, text=True, timeout=120).stdout


def local_idx_md5s(d):
    out = {}
    for p in glob.glob(os.path.join(cfg.ROOT, "logs", "runs", d, "*_idx.bin")):
        out[os.path.basename(p)] = hashlib.md5(open(p, "rb").read()).hexdigest()
    return out


def remote_dir_info(d):
    txt = ssh("cd %s/%s 2>/dev/null && ls -l | tail -n +2; echo ---MD5; cd %s/%s 2>/dev/null && md5sum *_idx.bin 2>/dev/null" % (SSD, d, SSD, d))
    files, md5s, part = [], {}, 0
    for line in txt.splitlines():
        if line.startswith("---MD5"):
            part = 1; continue
        p = line.split()
        if part == 0 and len(p) >= 9 and p[0].startswith("-"):
            files.append((p[-1], int(p[4])))
        elif part == 1 and len(p) == 2:
            md5s[p[1]] = p[0]
    return files, md5s


def free_gb():
    p = ssh("df -k %s | tail -1" % SSD).split()
    return int(p[3]) / 1e6 if len(p) >= 4 else -1.0


def decide(d, protect):
    m = NAME_RE.match(d)
    if not m:
        return "keep", "not one of ours"
    if m.group(1).startswith("KEEP_"):
        return "keep", "KEEP_ name"
    if protect and d == protect:
        return "keep", "run in progress"
    files, md5s = remote_dir_info(d)
    if not files:
        return "delete", "empty directory (failed run)"
    idx_remote = [f for f, _ in files if f.endswith("_idx.bin")]
    if not idx_remote:
        return "keep", "data files but no idx (%d files)" % len(files)
    local = local_idx_md5s(d)
    for f in idx_remote:
        if f not in local:
            return "keep", "no local copy of %s" % f
        if md5s.get(f) != local[f]:
            return "keep", "local copy of %s differs" % f
    size = sum(s for _, s in files)
    return "delete", "all %d idx files archived in logs/runs/%s; frees %.1f GB" % (len(idx_remote), d, size / 1e9)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dir", default=None, help="only this directory name")
    ap.add_argument("--protect", default=None, help="directory of the run in progress")
    ap.add_argument("--free", action="store_true", help="print the free GB on the SSD and exit")
    a = ap.parse_args()
    if a.free:
        print("%.1f" % free_gb()); return
    dirs = [a.dir] if a.dir else sorted(l.strip() for l in ssh("ls -1 %s" % SSD).splitlines() if l.strip().startswith("mmwcas_"))
    deleted, kept = [], []
    for d in dirs:
        action, why = decide(d, a.protect)
        if action == "delete" and not a.dry_run:
            assert d.startswith("mmwcas_") and "/" not in d and ".." not in d
            ssh("rm -rf '%s/%s'" % (SSD, d))
            still = ssh("ls -d %s/%s 2>/dev/null" % (SSD, d)).strip()
            print("DELETED %-45s %s%s" % (d, why, "" if not still else "  !! still present"))
            deleted.append(d)
        elif action == "delete":
            print("would delete %-40s %s" % (d, why)); deleted.append(d)
        else:
            print("keep    %-45s %s" % (d, why)); kept.append(d)
    print("-- %s: %d, kept: %d, free now %.1f GB" % ("would delete" if a.dry_run else "deleted", len(deleted), len(kept), free_gb()))


if __name__ == "__main__":
    main()
