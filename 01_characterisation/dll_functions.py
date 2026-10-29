"""List the functions your installed Kinesis DLLs provide for the KLD101 (LD_...) and TTC001 (TC_...).

  python 01_characterisation/dll_functions.py

Kinesis versions differ slightly in which functions they export. If a script says a function
is missing, run this and compare. It only reads the DLL files; no instrument is touched.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # repo root, for the oil852 package

import argparse  # noqa: E402
import struct  # noqa: E402
from pathlib import Path  # noqa: E402

from oil852.config import load_config  # noqa: E402

DLLS = {"KLD101": ("Thorlabs.MotionControl.KCube.LaserDiode.dll", "LD_"),
        "TTC001": ("Thorlabs.MotionControl.TCube.TEC.dll", "TC_")}


def pe_exports(path: Path) -> list[str]:
    """Names in a Windows DLL's export table (read straight from the file)."""
    b = path.read_bytes()
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    if b[pe:pe + 4] != b"PE\0\0":
        raise ValueError("not a PE file")
    n_sections, opt_size = struct.unpack_from("<H", b, pe + 6)[0], struct.unpack_from("<H", b, pe + 20)[0]
    opt = pe + 24
    magic = struct.unpack_from("<H", b, opt)[0]
    dd = opt + (96 if magic == 0x10B else 112)  # PE32 / PE32+
    exp_rva = struct.unpack_from("<I", b, dd)[0]
    if not exp_rva:
        return []
    sections = []
    for k in range(n_sections):
        s = opt + opt_size + 40 * k
        vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", b, s + 8)
        sections.append((vaddr, max(vsize, rsize), raddr))

    def off(rva):
        for vaddr, size, raddr in sections:
            if vaddr <= rva < vaddr + size:
                return rva - vaddr + raddr
        raise ValueError(f"RVA {rva:#x} outside sections")

    e = off(exp_rva)
    n_names, names_rva = struct.unpack_from("<I", b, e + 24)[0], struct.unpack_from("<I", b, e + 32)[0]
    out = []
    names = off(names_rva)
    for k in range(n_names):
        o = off(struct.unpack_from("<I", b, names + 4 * k)[0])
        out.append(b[o:b.index(b"\0", o)].decode("ascii", "replace"))
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default=None)
    a = p.parse_args()
    folder = Path(load_config(a.config)["driver"]["kinesis_path"])
    for dev, (dll, prefix) in DLLS.items():
        path = folder / dll
        if not path.exists():
            print(f"{dev}: {path} not found")
            continue
        names = sorted(n for n in pe_exports(path) if n.startswith(prefix))
        print(f"\n{dev} ({dll}): {len(names)} functions")
        print("  " + "\n  ".join(names))


if __name__ == "__main__":
    main()
