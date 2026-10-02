"""config.toml loads with every key the scripts use, and make_config.py writes complete Lua scripts with the expected chirp table."""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import cfg  # noqa: E402
from cascade_dsp.geometry import tx_order_from_lua  # noqa: E402


def test_config_keys():
    c = cfg.load()
    for key in ("pc.ip", "pc.python", "pc.ports", "pc.bind", "tda.ip", "tda.ssd", "tda.free_gb_min", "studio.dir", "studio.host", "studio.port",
                "studio.meta_image", "capture.samples", "capture.chirps", "capture.loops", "capture.period_ms", "follower.nice", "follower.poll_s"):
        assert cfg.get(key, c) is not None, key
    assert len(c["pc"]["ports"]) == 4 and all(isinstance(p, int) for p in c["pc"]["ports"])
    assert c["capture"]["samples"] * c["capture"]["chirps"] * c["capture"]["loops"] * 16 == 49152 * c["capture"]["loops"]


def test_make_config():
    out = tempfile.mkdtemp(prefix="lua_gen_")
    subprocess.check_call([sys.executable, os.path.join(ROOT, "tools", "make_config.py"), "--loops", "2", "--period-ms", "50",
                           "--capture-dir", "mmwcas_test", "--tag", "t", "--out-dir", out], stdout=subprocess.DEVNULL)
    full = open(os.path.join(out, "Cascade_Configuration_MIMO.lua")).read()
    reconf = open(os.path.join(out, "Cascade_Reconfig_t.lua")).read()
    start = open(os.path.join(out, "Cascade_StartCapture_t.lua")).read()
    c = cfg.load()
    assert 'TDA_IPAddress     =   "%s"' % c["tda"]["ip"] in full
    assert "nchirp_loops              =   2 " in full and "Inter_Frame_Interval      =   50 " in full
    assert "ar1.ConnectTDA(" in full and "ar1.ConnectTDA(" not in reconf
    assert "ar1.FrameConfig_mult(" in reconf and "nchirp_loops              =   2 " in reconf
    assert 'capture_directory               =   "mmwcas_test"' in start and "__" not in start
    assert tx_order_from_lua(os.path.join(out, "Cascade_Configuration_MIMO.lua")).tolist() == [12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]


if __name__ == "__main__":
    test_config_keys()
    test_make_config()
    print("all config tests passed")
