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
    def _declare(self):
        L = self._lib
        c = ctypes.c_char_p
        L.TLI_BuildDeviceList.restype = ctypes.c_short
        L.TLI_GetDeviceListByTypeExt.argtypes = [ctypes.c_char_p, ctypes.c_uint32, ctypes.c_int]
        L.TLI_GetDeviceListByTypeExt.restype = ctypes.c_short
        for name in ("LD_Open", "LD_SetOpenLoopMode", "LD_EnableOutput", "LD_DisableOutput",
                     "LD_RequestReadings", "LD_RequestStatusBits", "LD_RequestMaxCurrent",
                     "LD_RequestLaserPolarity", "LD_RequestSettings"):
            getattr(L, name).argtypes = [c]
            getattr(L, name).restype = ctypes.c_short
        L.LD_Close.argtypes = [c]
        L.LD_Close.restype = None
        L.LD_StartPolling.argtypes = [c, ctypes.c_int]
        L.LD_StartPolling.restype = ctypes.c_bool
        L.LD_StopPolling.argtypes = [c]
        L.LD_StopPolling.restype = None
        L.LD_SetLaserSetPoint.argtypes = [c, ctypes.c_uint16]
        L.LD_SetLaserSetPoint.restype = ctypes.c_short
        L.LD_GetLaserSetPoint.argtypes = [c]
        L.LD_GetLaserSetPoint.restype = ctypes.c_uint16
        L.LD_GetLaserDiodeCurrentReading.argtypes = [c]
        L.LD_GetLaserDiodeCurrentReading.restype = ctypes.c_int16  # documented as signed counts
        L.LD_GetVoltageReading.argtypes = [c]
        L.LD_GetVoltageReading.restype = ctypes.c_int16
        L.LD_GetPhotoCurrentReading.argtypes = [c]
        L.LD_GetPhotoCurrentReading.restype = ctypes.c_uint16
        L.LD_GetMaxCurrentDigPot.argtypes = [c]
        L.LD_GetMaxCurrentDigPot.restype = ctypes.c_uint16
        L.LD_GetStatusBits.argtypes = [c]
        L.LD_GetStatusBits.restype = ctypes.c_uint32

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
        self._lib.LD_StartPolling(self.serial, self.poll_ms)
        time.sleep(0.6)
        self._lib.LD_RequestSettings(self.serial)
        self._lib.LD_RequestMaxCurrent(self.serial)
        self._lib.LD_RequestLaserPolarity(self.serial)
        time.sleep(0.3)

    def close(self):
        if self._open:
            self._lib.LD_StopPolling(self.serial)
            self._lib.LD_Close(self.serial)
            self._open = False

    # ---- state --------------------------------------------------------------
    def status(self) -> DriverStatus:
        self._lib.LD_RequestStatusBits(self.serial)
        time.sleep(0.05)
        b = int(self._lib.LD_GetStatusBits(self.serial))
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
        pos = int(self._lib.LD_GetMaxCurrentDigPot(self.serial))
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
        self._check(self._lib.LD_SetOpenLoopMode(self.serial), "LD_SetOpenLoopMode")

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
        self._lib.LD_RequestReadings(self.serial)
        self._lib.LD_RequestStatusBits(self.serial)
        time.sleep(0.05)
        i_counts = int(self._lib.LD_GetLaserDiodeCurrentReading(self.serial))
        v_counts = int(self._lib.LD_GetVoltageReading(self.serial))
        pd_counts = int(self._lib.LD_GetPhotoCurrentReading(self.serial))
        tia = self._tia_range_mA(int(self._lib.LD_GetStatusBits(self.serial)))
        return DriverReading(
            current_mA=i_counts / FULL_COUNTS * self.full_scale_mA,
            voltage_V=v_counts / self.voltage_counts_per_V,
            pd_current_mA=(pd_counts / FULL_COUNTS * tia) if tia else None,
        )
