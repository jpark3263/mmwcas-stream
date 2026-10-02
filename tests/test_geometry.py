"""The virtual array must match TI's module_param.m; values hard-coded from MATLAB and re-checked against the .mat when present."""
import os
import sys

import numpy as np

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
from cascade_dsp.geometry import (CascadeGeometry, TX_TO_ENABLE, TI_CASCADE_RX_ID, assert_tx_order_from_lua,  # noqa: E402
                                  reorder_rx_to_physical, tx_order_from_lua)

MAT = os.path.join(ROOT, "validation", "ti_home_far_run_frame2.mat")
LUA = os.path.join(ROOT, "lua", "Cascade_Configuration_MIMO.template.lua")


def test_tx_order_from_lua():
    assert tx_order_from_lua(LUA).tolist() == [12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]
    assert_tx_order_from_lua(LUA)


def test_virtual_array_hardcoded():
    g = CascadeGeometry()
    assert g.d_tx.tolist() == [0, 4, 8, 12, 16, 20, 24, 28, 32, 9, 10, 11]
    assert g.d_tx_ele.tolist() == [0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 4, 6]
    assert g.d_rx.tolist() == [0, 1, 2, 3, 11, 12, 13, 14, 46, 47, 48, 49, 50, 51, 52, 53]
    assert g.D.shape == (192, 2)
    az0 = g.D[g.D[:, 1] == 0, 0]
    assert sorted(set(az0.tolist())) == list(range(86))
    assert len(g.antenna_azimuthonly) == 86
    assert np.all(np.diff(g.azimuth_positions) == 1) and g.azimuth_positions[0] == 0
    assert g.overlap_antenna_id.shape[0] == 58, g.overlap_antenna_id.shape
    for a, b, ta, tb in g.overlap_antenna_id:
        assert (g.D[a - 1] == g.D[b - 1]).all()
        assert ta != tb
    assert len(g.overlap_1tx) > 0


def test_rx_reorder():
    cube = np.arange(16)[:, None] * np.ones((16, 3))
    phys = reorder_rx_to_physical(cube, axis=0)
    assert phys[:, 0].astype(int).tolist() == (TI_CASCADE_RX_ID - 1).tolist()


def test_against_matlab_mat():
    if not os.path.exists(MAT):
        print("  (skipped: no %s; see extras/run_ti_parity.m)" % os.path.relpath(MAT, ROOT))
        return
    import h5py
    g = CascadeGeometry()
    with h5py.File(MAT, "r") as f:
        D = np.array(f["D"]).T
        aa = np.array(f["antenna_azimuthonly"]).ravel().astype(int)
        ov = np.array(f["overlapAntenna_ID"]).T.astype(int)
        tx = np.array(f["TxToEnable"]).ravel().astype(int)
        rxid = np.array(f["TI_RX_ID"]).ravel().astype(int)
    assert tx.tolist() == TX_TO_ENABLE.tolist()
    assert rxid.tolist() == TI_CASCADE_RX_ID.tolist()
    np.testing.assert_array_equal(D, g.D)
    np.testing.assert_array_equal(aa - 1, g.antenna_azimuthonly)
    np.testing.assert_array_equal(ov, g.overlap_antenna_id)
    print("  geometry equals MATLAB: D, antenna_azimuthonly (%d), overlap pairs (%d)" % (len(aa), len(ov)))


if __name__ == "__main__":
    test_tx_order_from_lua()
    test_virtual_array_hardcoded()
    test_rx_reorder()
    test_against_matlab_mat()
    print("all geometry tests passed")
