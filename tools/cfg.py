"""Reads config.toml (flat sections of strings, numbers, booleans and number lists); CLI: python tools/cfg.py section.key"""
import os
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PATH = os.path.join(ROOT, "config.toml")


def _value(text):
    text = text.strip()
    if text.startswith('"'):
        return text[1:text.index('"', 1)]
    if text.startswith("["):
        inner = text[1:text.index("]")]
        return [_value(x) for x in inner.split(",") if x.strip()]
    if text in ("true", "false"):
        return text == "true"
    text = text.split("#")[0].strip()
    return float(text) if "." in text else int(text)


def load(path=PATH):
    cfg = {}
    section = None
    for raw in open(path, encoding="utf-8"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            section = line[1:line.index("]")]
            cfg[section] = {}
            continue
        key, _, rest = line.partition("=")
        cfg[section][key.strip()] = _value(rest)
    return cfg


def get(dotted, cfg=None):
    section, key = dotted.split(".")
    return (cfg or load())[section][key]


if __name__ == "__main__":
    v = get(sys.argv[1])
    print(" ".join(str(x) for x in v) if isinstance(v, list) else v)
