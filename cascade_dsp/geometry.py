"""Antenna geometry and TDM-MIMO virtual array of the MMWCAS-RF-EVM (12 TX x 16 RX), constants from TI's module_param.m (THIRD_PARTY.md)."""
import re

import numpy as np

TI_CASCADE_TX_POSITION_AZI = np.array([11, 10, 9, 32, 28, 24, 20, 16, 12, 8, 4, 0])
TI_CASCADE_TX_POSITION_ELE = np.array([6, 4, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0])
TI_CASCADE_RX_POSITION_AZI = np.array(list(range(11, 15)) + list(range(50, 54)) + list(range(46, 50)) + list(range(0, 4)))
TI_CASCADE_RX_POSITION_ELE = np.zeros(16, dtype=int)
TI_CASCADE_RX_ID = np.array([13, 14, 15, 16, 1, 2, 3, 4, 9, 10, 11, 12, 5, 6, 7, 8])
TI_CASCADE_ANTENNA_DESIGN_FREQ_GHZ = 76.8
NUM_TX = 12
NUM_RX = 16
NUM_DEVICES = 4
TX_TO_ENABLE = np.array([12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1])
RX_PHYS_FROM_FILE = TI_CASCADE_RX_ID - 1


def reorder_rx_to_physical(cube_file_order, axis=0):
    return np.take(cube_file_order, RX_PHYS_FROM_FILE, axis=axis)


class CascadeGeometry:
    def __init__(self, tx_to_enable=TX_TO_ENABLE, rx_for_mimo=TI_CASCADE_RX_ID, center_freq_ghz=None):
        self.tx_to_enable = np.asarray(tx_to_enable)
        self.rx_for_mimo = np.asarray(rx_for_mimo)
        self.d_tx = TI_CASCADE_TX_POSITION_AZI[self.tx_to_enable - 1]
        self.d_tx_ele = TI_CASCADE_TX_POSITION_ELE[self.tx_to_enable - 1]
        self.d_rx = TI_CASCADE_RX_POSITION_AZI[self.rx_for_mimo - 1]
        self.d_rx_ele = TI_CASCADE_RX_POSITION_ELE[self.rx_for_mimo - 1]
        n_tx, n_rx = len(self.d_tx), len(self.d_rx)
        self.num_virtual = n_tx * n_rx
        azi = np.concatenate([self.d_rx + self.d_tx[i] for i in range(n_tx)])
        ele = np.concatenate([self.d_rx_ele + self.d_tx_ele[i] for i in range(n_tx)])
        self.D = np.stack([azi, ele], axis=1)
        self.tx_id_mimo = np.repeat(np.arange(1, n_tx + 1), n_rx)
        key = self.D[:, 0] * 10 + self.D[:, 1]
        _, first_idx = np.unique(key, return_index=True)
        repeat_idx = sorted(set(range(len(key))) - set(first_idx.tolist()))
        rows = []
        for r in repeat_idx:
            pair = np.where(key == key[r])[0]
            rows.append([pair[0] + 1, pair[1] + 1, self.tx_id_mimo[pair[0]], self.tx_id_mimo[pair[1]]])
        self.overlap_antenna_id = np.array(rows, dtype=int).reshape(-1, 4)
        dif = np.abs(self.overlap_antenna_id[:, 2] - self.overlap_antenna_id[:, 3]) if len(rows) else np.array([])
        self.overlap_1tx = self.overlap_antenna_id[dif == 1] if len(rows) else self.overlap_antenna_id
        self.overlap_2tx = self.overlap_antenna_id[dif == 2] if len(rows) else self.overlap_antenna_id
        self.overlap_3tx = self.overlap_antenna_id[dif == 3] if len(rows) else self.overlap_antenna_id
        ind0 = np.where(self.D[:, 1] == 0)[0]
        _, uniq = np.unique(self.D[ind0, 0], return_index=True)
        self.antenna_azimuthonly = ind0[uniq]
        self.azimuth_positions = self.D[self.antenna_azimuthonly, 0]
        self.center_freq_ghz = center_freq_ghz
        self.d_optimal = (0.5 * center_freq_ghz / TI_CASCADE_ANTENNA_DESIGN_FREQ_GHZ) if center_freq_ghz else 0.5

    def azimuth_row(self, virtual_channels_vec):
        ind0 = np.where(self.D[:, 1] == 0)[0]
        pos = self.D[ind0, 0]
        upos = np.unique(pos)
        out = np.zeros(virtual_channels_vec.shape[:-1] + (len(upos),), dtype=np.complex64)
        for k, p in enumerate(upos):
            sel = ind0[pos == p]
            out[..., k] = virtual_channels_vec[..., sel].mean(axis=-1)
        return out, upos


def tx_order_from_lua(lua_path):
    txt = open(lua_path, encoding="latin-1").read()
    body = txt[txt.find("function Configure_Chirps"):]
    end = body.find("\nend", 1)
    body = body[:end if end > 0 else None]
    dev = None
    table = {}
    for line in body.splitlines():
        m = re.search(r"if\s*\(\s*i\s*==\s*(\d)\s*\)", line)
        if m:
            dev = int(m.group(1))
            continue
        m = re.search(r"ChirpConfig_mult\(\s*dev_list\[i\]\s*,\s*(\d+)\s*,\s*(\d+)\s*,(?:\s*[-\d.]+\s*,){5}\s*(\d)\s*,\s*(\d)\s*,\s*(\d)\s*\)", line)
        if m and dev is not None:
            c0, c1, t0, t1, t2 = (int(x) for x in m.groups())
            for c in range(c0, c1 + 1):
                for tx, en in enumerate((t0, t1, t2)):
                    if en:
                        table.setdefault(c, []).append((dev - 1) * 3 + tx + 1)
    chirps = sorted(table)
    if not chirps:
        raise ValueError("no ChirpConfig_mult table found in %s" % lua_path)
    order = []
    for c in chirps:
        if len(table[c]) != 1:
            raise ValueError("chirp %d enables %d TXs (expected exactly 1): %s" % (c, len(table[c]), table[c]))
        order.append(table[c][0])
    return np.array(order)


def assert_tx_order_from_lua(lua_path, expected=TX_TO_ENABLE):
    got = tx_order_from_lua(lua_path)
    if not np.array_equal(got, expected):
        raise AssertionError("TX order in %s is %s, code expects %s" % (lua_path, got.tolist(), np.asarray(expected).tolist()))
    return got
