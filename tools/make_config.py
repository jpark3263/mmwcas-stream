"""Writes the per-run Lua scripts to lua/generated/ from the templates and config.toml: full configuration, reconfig (profile/chirp/frame only) and start-capture."""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cfg  # noqa: E402

LUA = os.path.join(cfg.ROOT, "lua")
API_MARKER = "------------------------------ API Configuration ------------------------------------------------"
SENSOR_MARKER = "---------------------------Sensor Configuration-------------------------"


def fill(text, values):
    for k, v in values.items():
        text = text.replace("__%s__" % k, str(v))
    assert not re.search(r"__[A-Z_]+__", text), "unfilled placeholder in template"
    return text


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path


def main():
    c = cfg.load()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--loops", type=int, default=c["capture"]["loops"])
    ap.add_argument("--period-ms", type=int, default=c["capture"]["period_ms"])
    ap.add_argument("--capture-dir", default=None, help="name of the capture directory on the SSD (writes the start script)")
    ap.add_argument("--tag", default="", help="suffix of the generated reconfig/start scripts (unique per run)")
    ap.add_argument("--out-dir", default=os.path.join(LUA, "generated"))
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    values = dict(META_IMAGE=c["studio"]["meta_image"].replace("/", "\\\\"), TDA_IP=c["tda"]["ip"], LOOPS=a.loops, PERIOD_MS=a.period_ms)
    src = fill(open(os.path.join(LUA, "Cascade_Configuration_MIMO.template.lua"), encoding="utf-8").read(), values)
    assert src.count(API_MARKER) == 1 and src.count(SENSOR_MARKER) == 1
    suffix = ("_" + a.tag) if a.tag else ""
    out = [write(os.path.join(a.out_dir, "Cascade_Configuration_MIMO.lua"), src)]
    head = src[:src.index(API_MARKER)]
    sensor = src[src.index(SENSOR_MARKER):]
    reconfig = head + "\n" + sensor + '\nWriteToLog("Reconfig done: %d loop(s), %d ms\\n", "blue")\n' % (a.loops, a.period_ms)
    out.append(write(os.path.join(a.out_dir, "Cascade_Reconfig%s.lua" % suffix), reconfig))
    if a.capture_dir:
        start = fill(open(os.path.join(LUA, "Cascade_StartCapture.template.lua"), encoding="utf-8").read(), dict(CAPTURE_DIRECTORY=a.capture_dir))
        out.append(write(os.path.join(a.out_dir, "Cascade_StartCapture%s.lua" % suffix), start))
    for p in out:
        print(os.path.relpath(p, cfg.ROOT).replace("\\", "/"))


if __name__ == "__main__":
    main()
