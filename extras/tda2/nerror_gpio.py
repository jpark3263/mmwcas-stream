#!/usr/bin/python
# Runs on the TDA2 (Python 2.7, read-only /dev/mem): samples the radar nERROR line TDA_GPIO2_19. Usage: python nerror_gpio.py [INTERVAL_S DURATION_S]
import mmap, os, struct, sys, time

CLKCTRL = 0x4A009760
GPIO2 = 0x48055000
BIT = 19


def rd32(addr):
    fd = os.open("/dev/mem", os.O_RDONLY | os.O_SYNC)
    try:
        page = addr & ~0xFFF
        m = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED, mmap.PROT_READ, offset=page)
        try:
            return struct.unpack("<I", m[addr - page:addr - page + 4])[0]
        finally:
            m.close()
    finally:
        os.close(fd)


def sample():
    up = open("/proc/uptime").read().split()[0]
    clk = rd32(CLKCTRL)
    idlest = (clk >> 16) & 3
    modulemode = clk & 3
    bank_disabled = modulemode == 0 or idlest == 3
    if bank_disabled:
        return "%s clk=0x%08x idlest=%d modulemode=%d (bank disabled, registers not read)" % (up, clk, idlest, modulemode)
    oe = rd32(GPIO2 + 0x134); din = rd32(GPIO2 + 0x138); dout = rd32(GPIO2 + 0x13C)
    b = lambda v: (v >> BIT) & 1
    return "%s clk=0x%08x idlest=%d oe19=%d din19=%d dout19=%d nERROR=%s" % (up, clk, idlest, b(oe), b(din), b(dout), "LOW(asserted)" if b(din) == 0 else "HIGH")


def main():
    if len(sys.argv) >= 3:
        interval, duration = float(sys.argv[1]), float(sys.argv[2])
        t_end = time.time() + duration
        while time.time() < t_end:
            sys.stdout.write("### " + sample() + "\n"); sys.stdout.flush()
            time.sleep(interval)
    else:
        print(sample())


if __name__ == "__main__":
    main()
