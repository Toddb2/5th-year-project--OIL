"""Thorlabs KLD101 K-Cube laser diode driver, controlled through the Kinesis C DLL.

Function names and scalings follow Thorlabs.MotionControl.KCube.LaserDiode.h from
Thorlabs' Motion_Control_Examples repository:

- set point: 0-32767 counts = 0-230 mA in constant-current (open loop) mode
- current reading: signed, 32767 counts = 230 mA
- photodiode reading: 0-32767 counts = 0 to the TIA range
- hardware current limit: digital pot 20-255 = 17.3-230 mA
- status bits: see STATUS_* constants below

Windows only (the DLL is Windows-only). Use 64-bit Python with 64-bit Kinesis.
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from pathlib import Path

from .base import DriverReading, DriverStatus

KLD_TYPE_ID = 98  # serial-number prefix for KLD101

STATUS_OUTPUT_ENABLED = 0x00000001
STATUS_KEY_SWITCH = 0x00000002
STATUS_CONSTANT_POWER = 0x00000004
STATUS_INTERLOCK = 0x00000008
STATUS_TIA_10uA = 0x00000010
STATUS_TIA_100uA = 0x00000020
STATUS_TIA_1mA = 0x00000040
STATUS_TIA_10mA = 0x00000080
STATUS_CATHODE_GROUNDED = 0x00000100
STATUS_CURRENT_LIMIT = 0x00000400
STATUS_OPEN_CIRCUIT = 0x00000800
STATUS_PSU_OK = 0x00001000

FULL_COUNTS = 32767
DLL_NAME = "Thorlabs.MotionControl.KCube.LaserDiode.dll"


class KLD101Error(RuntimeError):
    pass


class KLD101:
    def __init__(self, serial: str, kinesis_path: str, full_scale_mA: float = 230.0,
                 voltage_counts_per_V: float = 1000.0, poll_ms: int = 100):
        if sys.platform != "win32":
            raise KLD101Error("The Kinesis DLL only runs on Windows. Use --sim or --manual elsewhere.")
        self.serial = serial.encode()
        self.full_scale_mA = full_scale_mA
        self.voltage_counts_per_V = voltage_counts_per_V
        self.poll_ms = poll_ms
        path = Path(kinesis_path)
        if not (path / DLL_NAME).exists():
            raise KLD101Error(f"{DLL_NAME} not found in {path}. Install Kinesis or fix kinesis_path in config/bench.toml.")
        os.add_dll_directory(str(path))
        self._lib = ctypes.CDLL(str(path / DLL_NAME))
        self._declare()
        self._open = False

    # ---- ctypes signatures ------------------------------------------------
    # Functions the driver cannot work without, and extras that differ between Kinesis versions.
    REQUIRED = ("LD_Open", "LD_Close", "LD_StartPolling", "LD_StopPolling", "LD_EnableOutput", "LD_DisableOutput",
                "LD_SetLaserSetPoint", "LD_RequestStatusBits", "LD_GetStatusBits")

    def _declare(self):
        L = self._lib
        c = ctypes.c_char_p
        sig = {
            "LD_Open": ([c], ctypes.c_short), "LD_Close": ([c], None),
            "LD_StartPolling": ([c, ctypes.c_int], ctypes.c_bool), "LD_StopPolling": ([c], None),
            "LD_SetOpenLoopMode": ([c], ctypes.c_short), "LD_EnableOutput": ([c], ctypes.c_short),
            "LD_DisableOutput": ([c], ctypes.c_short), "LD_RequestReadings": ([c], ctypes.c_short),
            "LD_RequestStatusBits": ([c], ctypes.c_short), "LD_RequestMaxCurrent": ([c], ctypes.c_short),
            "LD_RequestStatus": ([c], ctypes.c_short),
            "LD_RequestLaserPolarity": ([c], ctypes.c_short), "LD_RequestSettings": ([c], ctypes.c_short),
            "LD_SetLaserSetPoint": ([c, ctypes.c_uint16], ctypes.c_short),
            "LD_GetLaserSetPoint": ([c], ctypes.c_uint16),
            "LD_GetLaserDiodeCurrentReading": ([c], ctypes.c_int16),  # documented as signed counts
            "LD_GetVoltageReading": ([c], ctypes.c_int16),
            "LD_GetPhotoCurrentReading": ([c], ctypes.c_uint16),
            "LD_GetMaxCurrentDigPot": ([c], ctypes.c_uint16),
            "LD_GetStatusBits": ([c], ctypes.c_uint32),
        }
        self._has = set()
        for name, (args, res) in sig.items():
            try:
                f = getattr(L, name)
            except AttributeError:
                continue
            f.argtypes, f.restype = args, res
            self._has.add(name)
        L.TLI_BuildDeviceList.restype = ctypes.c_short
        L.TLI_GetDeviceListByTypeExt.argtypes = [ctypes.c_char_p, ctypes.c_uint32, ctypes.c_int]
        L.TLI_GetDeviceListByTypeExt.restype = ctypes.c_short
        missing = [n for n in self.REQUIRED if n not in self._has]
        if missing:
            raise KLD101Error(f"Kinesis DLL lacks {', '.join(missing)}. Run "
                              "python 01_characterisation/dll_functions.py and send the output.")

    def _call(self, name, *args, default=None):
        """Call an optional DLL function; return default if this Kinesis version doesn't have it."""
        if name not in self._has:
            return default
        return getattr(self._lib, name)(self.serial, *args)

    def _check(self, code: int, what: str):
        if code != 0:
            raise KLD101Error(f"{what} failed with Kinesis error code {code}")

    # ---- connection -------------------------------------------------------
    def connect(self):
        self._check(self._lib.TLI_BuildDeviceList(), "TLI_BuildDeviceList")
        buf = ctypes.create_string_buffer(512)
        self._lib.TLI_GetDeviceListByTypeExt(buf, 512, KLD_TYPE_ID)
        found = [s for s in buf.value.decode().split(",") if s]
        if self.serial.decode() not in found:
            raise KLD101Error(f"KLD101 {self.serial.decode()} not found. Connected KLD101s: {found or 'none'}. "
                              "Close the Kinesis app (it holds the USB connection) and check the serial in config/bench.toml.")
        self._check(self._lib.LD_Open(self.serial), "LD_Open")
        self._open = True
        try:
            self._after_open()
        except BaseException:
            self.close()  # never leave the K-Cube held open after a failed connect
            raise

    def _after_open(self):
        self._lib.LD_StartPolling(self.serial, self.poll_ms)
        time.sleep(0.6)
        self._call("LD_RequestSettings")
        self._call("LD_RequestMaxCurrent")
        self._call("LD_RequestLaserPolarity")
        time.sleep(0.3)

    def close(self):
        if self._open:
            self._lib.LD_StopPolling(self.serial)
            self._lib.LD_Close(self.serial)
            self._open = False

    # ---- state --------------------------------------------------------------
    def status(self) -> DriverStatus:
        b = 0
        for _ in range(10):  # right after connecting the bits can still read 0 (not yet reported)
            self._lib.LD_RequestStatusBits(self.serial)
            time.sleep(0.15)
            b = int(self._lib.LD_GetStatusBits(self.serial))
            if b:
                break
        return DriverStatus(
            output_enabled=bool(b & STATUS_OUTPUT_ENABLED),
            interlock_ok=bool(b & STATUS_INTERLOCK),
            key_switch_on=bool(b & STATUS_KEY_SWITCH),
            constant_power_mode=bool(b & STATUS_CONSTANT_POWER),
            polarity="cathode_grounded" if b & STATUS_CATHODE_GROUNDED else "anode_grounded",
            current_limit_reached=bool(b & STATUS_CURRENT_LIMIT),
            open_circuit=bool(b & STATUS_OPEN_CIRCUIT),
            psu_ok=bool(b & STATUS_PSU_OK),
            raw_bits=b,
        )

    def hardware_limit_mA(self) -> float | None:
        """Current limit set on the K-Cube itself (digital pot 20-255 = 17.3-230 mA, assumed linear)."""
        pos = self._call("LD_GetMaxCurrentDigPot")
        if pos is None:
            return None  # not available in this Kinesis version; the K-Cube still enforces its own limit
        pos = int(pos)
        if pos < 20 or pos > 255:
            return None
        return 17.3 + (pos - 20) * (230.0 - 17.3) / (255 - 20)

    def _tia_range_mA(self, bits: int) -> float | None:
        for flag, rng in ((STATUS_TIA_10uA, 0.01), (STATUS_TIA_100uA, 0.1),
                          (STATUS_TIA_1mA, 1.0), (STATUS_TIA_10mA, 10.0)):
            if bits & flag:
                return rng
        return None

    # ---- control ----------------------------------------------------------
    def set_constant_current(self):
        if "LD_SetOpenLoopMode" in self._has:
            self._check(self._lib.LD_SetOpenLoopMode(self.serial), "LD_SetOpenLoopMode")
        # otherwise the mode set in Kinesis is used; status() still refuses constant-power mode

    def enable(self):
        self._check(self._lib.LD_EnableOutput(self.serial), "LD_EnableOutput")

    def disable(self):
        self._lib.LD_SetLaserSetPoint(self.serial, 0)
        self._lib.LD_DisableOutput(self.serial)

    def set_current_mA(self, mA: float):
        if mA < 0 or mA > self.full_scale_mA:
            raise KLD101Error(f"Set point {mA} mA outside 0-{self.full_scale_mA} mA")
        counts = int(round(mA / self.full_scale_mA * FULL_COUNTS))
        self._check(self._lib.LD_SetLaserSetPoint(self.serial, counts), "LD_SetLaserSetPoint")

    def read(self) -> DriverReading:
        self._call("LD_RequestReadings")
        self._call("LD_RequestStatus")  # header: "actual power, current and status"; Kinesis' own display uses it
        self._lib.LD_RequestStatusBits(self.serial)
        time.sleep(0.15)
        i_counts = self._call("LD_GetLaserDiodeCurrentReading")
        if i_counts is None:  # fall back to the set point if this Kinesis can't read the current back
            i_counts = self._call("LD_GetLaserSetPoint", default=0)
        v_counts = self._call("LD_GetVoltageReading")
        pd_counts = self._call("LD_GetPhotoCurrentReading")
        tia = self._tia_range_mA(int(self._lib.LD_GetStatusBits(self.serial)))
        return DriverReading(
            current_mA=int(i_counts) / FULL_COUNTS * self.full_scale_mA,
            voltage_V=None if v_counts is None else int(v_counts) / self.voltage_counts_per_V,
            pd_current_mA=(int(pd_counts) / FULL_COUNTS * tia) if (tia and pd_counts is not None) else None,
        )
