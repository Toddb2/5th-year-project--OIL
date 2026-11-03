"""TEC controllers for the laser temperature: the Thorlabs TTC001 T-Cube (through the Kinesis C DLL),
a manual stand-in (you set it on the front panel) and a simulated one.

TTC001 calls follow Thorlabs.MotionControl.TCube.TEC.h (Kinesis), as used in the itom
ThorlabsTCubeTEC plugin:
- device type prefix 87
- TC_GetTemperatureReading / TC_GetTemperatureSet / TC_SetTemperature use hundredths of the
  display unit: kOhm for a thermistor, deg C for an AD590/AD592 transducer
- sensor types: 0 = transducer, 1 = TH20kOhm, 2 = TH200kOhm
- TC_GetCurrentLimit / TC_SetCurrentLimit in mA

Windows only. Close the Kinesis app first: it holds the USB connection.
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from pathlib import Path

from ..thermistor import resistance_kohm, temperature_C

TEC_TYPE_ID = 87
DLL_NAME = "Thorlabs.MotionControl.TCube.TEC.dll"
SENSOR_CODES = {"Transducer": 0, "TH20kOhm": 1, "TH200kOhm": 2}


class TECError(RuntimeError):
    pass


class _LoopParams(ctypes.Structure):
    """TC_LoopParameters from Thorlabs.MotionControl.TCube.TEC.h (packed, three WORDs)."""
    _pack_ = 1
    _fields_ = [("proportionalGain", ctypes.c_ushort), ("integralGain", ctypes.c_ushort),
                ("differentialGain", ctypes.c_ushort)]


class _TECBase:
    """Shared temperature conversion, limits and the settle/runaway check."""

    def __init__(self, sensor: str = "TH20kOhm", r25_kohm: float = 10.0, beta_K: float = 3950.0,
                 min_C: float = 15.0, max_C: float = 35.0):
        if sensor not in SENSOR_CODES:
            raise TECError(f"Unknown sensor '{sensor}'. Use one of {list(SENSOR_CODES)}")
        self.sensor = sensor
        self.r25_kohm = r25_kohm
        self.beta_K = beta_K
        self.min_C = min_C
        self.max_C = max_C

    @property
    def thermistor(self) -> bool:
        return self.sensor != "Transducer"

    def to_display(self, temp_C: float) -> float:
        """Value the TTC001 works in: kOhm for a thermistor, deg C for a transducer."""
        return resistance_kohm(temp_C, self.r25_kohm, self.beta_K) if self.thermistor else temp_C

    def from_display(self, value: float) -> float:
        return temperature_C(value, self.r25_kohm, self.beta_K) if self.thermistor else value

    def check_range(self, temp_C: float):
        if not (self.min_C <= temp_C <= self.max_C):
            raise TECError(f"{temp_C:g} C is outside the allowed {self.min_C:g}-{self.max_C:g} C "
                           "(config/bench.toml [tec] min_C / max_C). Below ~15 C risks condensation.")

    def describe(self, temp_C: float) -> str:
        if self.thermistor:
            return f"{temp_C:g} C (= {self.to_display(temp_C):.2f} kOhm on the TTC001 display)"
        return f"{temp_C:g} C"

    def _current_str(self) -> str:
        try:
            return f", TEC {self.tec_current_A() * 1000:+5.0f} mA"
        except Exception:
            return ""

    def _check_bounds(self, T: float):
        """Hard limits, whatever the cause: well outside the allowed range means something is wrong."""
        if T < self.min_C - 3 or T > self.max_C + 5:
            self.disable()
            raise TECError(f"Temperature {T:.2f} C is outside the safe range ({self.min_C - 3:g}-{self.max_C + 5:g} C). "
                           "TEC output disabled. Check the TEC wiring (TEC+ and TEC- swapped?) and the heatsink.")

    def wait_until_stable(self, target_C: float, tol_C: float = 0.05, hold_s: float = 30.0,
                          timeout_s: float = 900.0, diverge_s: float = 120.0, poll_s: float = 1.0,
                          average_s: float = 0.0) -> float:
        """Wait until the reading stays within tol_C of target for hold_s.

        With average_s > 0 the test uses the mean of the last average_s seconds instead of each
        reading, for a loop that cycles about the right temperature (the bench TTC001 in Nov 2026).
        The swing over that window is kept in self.last_swing_C.

        Overshoot is normal after a change, so the runaway check only trips if the error has kept
        growing for diverge_s (TEC+ and TEC- swapped), or the temperature leaves the safe range.
        """
        t0 = time.time()
        hist: list[tuple[float, float]] = []
        window: list[tuple[float, float]] = []
        stable_since = None
        last_print = 0.0
        self.last_swing_C = None
        if average_s > 0:
            poll_s = min(poll_s, 0.25)
        while True:
            T_now = self.read_C()
            now = time.time()
            self._check_bounds(T_now)
            if average_s > 0:
                window.append((now, T_now))
                window = [w for w in window if w[0] >= now - average_s]
                vals = [w[1] for w in window]
                T = sum(vals) / len(vals)
                self.last_swing_C = max(vals) - min(vals)
                err = abs(T - target_C) if now - t0 >= average_s else float("inf")
            else:
                T = T_now
                err = abs(T - target_C)
            hist.append((now, abs(T_now - target_C)))
            hist = [h for h in hist if h[0] >= now - diverge_s]
            if now - t0 >= diverge_s and len(hist) > 3:
                errs = [e for _, e in hist]
                still_growing = errs[-1] >= max(errs) - 0.1 and min(errs) >= errs[0] - 0.1
                if still_growing and errs[-1] - errs[0] > 1.0 and errs[-1] > 2.0:
                    self.disable()
                    raise TECError(f"Temperature has moved steadily away from {target_C:g} C for {diverge_s:g} s "
                                   f"(now {T:.2f} C). TEC output disabled. TEC+ and TEC- are probably swapped.")
            if err <= tol_C:
                stable_since = stable_since or now
                if now - stable_since >= hold_s:
                    sw = f", {average_s:g} s mean, swinging {self.last_swing_C:.2f} C" if average_s > 0 else ""
                    print(f"\r  TEC stable at {T:.3f} C (target {target_C:g} C{sw})                        ")
                    return T
            else:
                stable_since = None
            if now - t0 > timeout_s:
                raise TECError(f"TEC did not settle within {timeout_s:g} s (at {T:.2f} C, target {target_C:g} C). "
                               "If it keeps swinging either side of the target, lower the TTC001 loop gains in Kinesis; "
                               "if it never gets there, check the current limit and the heatsink.")
            if now - last_print > 2:
                held = f", holding {now - stable_since:4.0f}/{hold_s:g} s" if stable_since else ""
                mean = f" (mean, swing {self.last_swing_C:.2f})" if average_s > 0 else ""
                print(f"\r  TEC {T:7.3f} C{mean} -> {target_C:g} C{self._current_str()}{held}      ", end="", flush=True)
                last_print = now
            time.sleep(poll_s)

    def go_to(self, temp_C: float, tol_C: float = 0.05, hold_s: float = 30.0, timeout_s: float = 900.0,
              ramp_C_per_min: float | None = 3.0, average_s: float = 0.0) -> float:
        """Move the set point gradually (less overshoot and integral wind-up), then wait to settle."""
        self.check_range(temp_C)
        if ramp_C_per_min:
            sp = self.read_C()
            if not self.is_enabled():
                self.set_C(min(max(sp, self.min_C), self.max_C))
                self.enable()
            step = ramp_C_per_min * 10.0 / 60.0  # one set-point move every 10 s
            while abs(temp_C - sp) > step:
                sp += step if temp_C > sp else -step
                self.set_C(min(max(sp, self.min_C), self.max_C))
                for _ in range(10):
                    T = self.read_C()
                    self._check_bounds(T)
                    print(f"\r  TEC {T:7.3f} C, set point ramping {sp:6.2f} -> {temp_C:g} C{self._current_str()}   ",
                          end="", flush=True)
                    time.sleep(1.0)
        self.set_C(temp_C)
        if not self.is_enabled():
            self.enable()
        return self.wait_until_stable(temp_C, tol_C, hold_s, timeout_s, average_s=average_s)


class TTC001(_TECBase):
    def __init__(self, serial: str, kinesis_path: str, poll_ms: int = 200, **kw):
        super().__init__(**kw)
        if sys.platform != "win32":
            raise TECError("The Kinesis DLL only runs on Windows. Use sim or manual TEC control elsewhere.")
        self.serial = str(serial).encode()
        self.poll_ms = poll_ms
        path = Path(kinesis_path)
        if not (path / DLL_NAME).exists():
            raise TECError(f"{DLL_NAME} not found in {path}. Install Kinesis or fix kinesis_path in config/bench.toml.")
        os.add_dll_directory(str(path))
        self._lib = ctypes.CDLL(str(path / DLL_NAME))
        self._declare()
        self._open = False
        self._enabled = None

    def _declare(self):
        L, c = self._lib, ctypes.c_char_p
        L.TLI_BuildDeviceList.restype = ctypes.c_short
        L.TLI_GetDeviceListByTypeExt.argtypes = [ctypes.c_char_p, ctypes.c_uint32, ctypes.c_int]
        L.TLI_GetDeviceListByTypeExt.restype = ctypes.c_short
        for name in ("TC_Open", "TC_Enable", "TC_Disable"):
            getattr(L, name).argtypes = [c]
            getattr(L, name).restype = ctypes.c_short
        L.TC_Close.argtypes = [c]
        L.TC_Close.restype = None
        L.TC_StartPolling.argtypes = [c, ctypes.c_int]
        L.TC_StartPolling.restype = ctypes.c_bool
        L.TC_StopPolling.argtypes = [c]
        L.TC_StopPolling.restype = None
        L.TC_GetTemperatureReading.argtypes = [c]
        L.TC_GetTemperatureReading.restype = ctypes.c_int16
        L.TC_GetTemperatureSet.argtypes = [c]
        L.TC_GetTemperatureSet.restype = ctypes.c_int16
        L.TC_SetTemperature.argtypes = [c, ctypes.c_int16]
        L.TC_SetTemperature.restype = ctypes.c_short
        L.TC_GetSensorType.argtypes = [c]
        L.TC_GetSensorType.restype = ctypes.c_int
        L.TC_SetSensorType.argtypes = [c, ctypes.c_int]
        L.TC_SetSensorType.restype = ctypes.c_short
        L.TC_GetCurrentLimit.argtypes = [c]
        L.TC_GetCurrentLimit.restype = ctypes.c_uint16
        L.TC_GetCurrentReading.argtypes = [c]
        L.TC_GetCurrentReading.restype = ctypes.c_int16  # mA; sign shows heating or cooling
        if hasattr(L, "TC_RequestReadings"):
            L.TC_RequestReadings.argtypes = [c]
            L.TC_RequestReadings.restype = ctypes.c_short
        for name in ("TC_GetTempLoopParams", "TC_SetTempLoopParams"):
            if hasattr(L, name):
                getattr(L, name).argtypes = [c, ctypes.POINTER(_LoopParams)]
                getattr(L, name).restype = ctypes.c_short
        if hasattr(L, "TC_RequestTempLoopParams"):
            L.TC_RequestTempLoopParams.argtypes = [c]
            L.TC_RequestTempLoopParams.restype = ctypes.c_short
        if hasattr(L, "TC_PersistSettings"):
            L.TC_PersistSettings.argtypes = [c]
            L.TC_PersistSettings.restype = ctypes.c_bool

    def connect(self):
        if self._lib.TLI_BuildDeviceList() != 0:
            raise TECError("TLI_BuildDeviceList failed")
        buf = ctypes.create_string_buffer(512)
        self._lib.TLI_GetDeviceListByTypeExt(buf, 512, TEC_TYPE_ID)
        found = [s for s in buf.value.decode().split(",") if s]
        if self.serial.decode() not in found:
            raise TECError(f"TTC001 {self.serial.decode()} not found. Connected TTC001s: {found or 'none'}. "
                           "Close the Kinesis app and check [tec] serial in config/bench.toml.")
        code = self._lib.TC_Open(self.serial)
        if code != 0:
            raise TECError(f"TC_Open failed with Kinesis error code {code}")
        self._open = True
        try:
            self._after_open()
        except BaseException:
            self.close()  # never leave the T-Cube held open after a failed connect
            raise

    def _after_open(self):
        # Not TC_LoadSettings: that applies the Kinesis startup settings, which may say "Transducer".
        self._lib.TC_StartPolling(self.serial, self.poll_ms)
        time.sleep(1.0)
        got = int(self._lib.TC_GetSensorType(self.serial))
        want = SENSOR_CODES[self.sensor]
        names = {v: k for k, v in SENSOR_CODES.items()}
        if got != want:
            print(f"  TTC001 sensor type was {names.get(got, got)}; setting {self.sensor}.")
            self._lib.TC_SetSensorType(self.serial, want)
        # readings arrive with polling; give it a few seconds after connecting or a sensor change
        raw, t0 = 0.0, time.time()
        while time.time() - t0 < 5.0:
            if hasattr(self._lib, "TC_RequestReadings"):
                self._lib.TC_RequestReadings(self.serial)
            time.sleep(0.5)
            raw = self.read_display()
            if raw != 0:
                break
        if self.thermistor and not (0.3 < raw < 150):
            now = names.get(int(self._lib.TC_GetSensorType(self.serial)), "?")
            raise TECError(f"TTC001 reads {raw:.2f} (sensor type now {now}). If Kinesis shows ~10-12 kOhm, close "
                           "Kinesis and retry; otherwise no thermistor is seen on pins 3/4.")

    def close(self):
        if self._open:
            self._lib.TC_StopPolling(self.serial)
            self._lib.TC_Close(self.serial)
            self._open = False

    def read_display(self) -> float:
        return int(self._lib.TC_GetTemperatureReading(self.serial)) / 100.0

    def read_C(self) -> float:
        return self.from_display(self.read_display())

    def setpoint_C(self) -> float:
        return self.from_display(int(self._lib.TC_GetTemperatureSet(self.serial)) / 100.0)

    def set_C(self, temp_C: float):
        self.check_range(temp_C)
        counts = int(round(self.to_display(temp_C) * 100))
        code = self._lib.TC_SetTemperature(self.serial, counts)
        if code != 0:
            raise TECError(f"TC_SetTemperature failed with Kinesis error code {code}")

    def current_limit_A(self) -> float:
        return int(self._lib.TC_GetCurrentLimit(self.serial)) / 1000.0

    def tec_current_A(self) -> float:
        return int(self._lib.TC_GetCurrentReading(self.serial)) / 1000.0

    # ---- loop gains (P, I, D) -------------------------------------------------------
    # The header says 1..32767 = 1..100, but other users report the raw values match the Kinesis
    # panel (e.g. P 15). The units are worked out from the first read: raw values above 100 must
    # be counts. Everything here is in Kinesis-panel units.
    def loop_gains_raw(self) -> tuple[int, int, int]:
        if not hasattr(self._lib, "TC_GetTempLoopParams"):
            raise TECError("This Kinesis version has no TC_GetTempLoopParams; set the gains in Kinesis.")
        if hasattr(self._lib, "TC_RequestTempLoopParams"):
            self._lib.TC_RequestTempLoopParams(self.serial)
            time.sleep(0.4)
        lp = _LoopParams()
        code = self._lib.TC_GetTempLoopParams(self.serial, ctypes.byref(lp))
        if code != 0:
            raise TECError(f"TC_GetTempLoopParams failed with Kinesis error code {code}")
        return int(lp.proportionalGain), int(lp.integralGain), int(lp.differentialGain)

    def _gain_scale(self) -> float:
        if getattr(self, "_scale", None) is None:
            raw = self.loop_gains_raw()
            self._scale = 32767 / 100 if max(raw) > 100 else 1.0
        return self._scale

    def loop_gains(self) -> tuple[float, float, float]:
        sc = self._gain_scale()
        return tuple(round(v / sc, 2) for v in self.loop_gains_raw())

    def set_loop_gains(self, p: float, i: float, d: float):
        if not (1 <= p <= 100 and 0 <= i <= 100 and 0 <= d <= 100):
            raise TECError("Gains out of range (P 1-100, I 0-100, D 0-100)")
        sc = self._gain_scale()
        lp = _LoopParams(int(round(p * sc)), int(round(i * sc)), int(round(d * sc)))
        code = self._lib.TC_SetTempLoopParams(self.serial, ctypes.byref(lp))
        if code != 0:
            raise TECError(f"TC_SetTempLoopParams failed with Kinesis error code {code}")

    def persist(self) -> bool:
        return bool(self._lib.TC_PersistSettings(self.serial)) if hasattr(self._lib, "TC_PersistSettings") else False

    def is_enabled(self) -> bool:
        return bool(self._enabled)

    def enable(self):
        code = self._lib.TC_Enable(self.serial)
        if code != 0:
            raise TECError(f"TC_Enable failed with Kinesis error code {code}")
        self._enabled = True

    def disable(self):
        self._lib.TC_Disable(self.serial)
        self._enabled = False


class ManualTEC(_TECBase):
    """You set the TTC001 front panel; the script waits for you."""

    def connect(self):
        print("Manual TEC: set the TTC001 yourself when asked.")
        self._T = None

    def close(self):
        pass

    def read_C(self) -> float:
        return self._T if self._T is not None else float("nan")

    def set_C(self, temp_C: float):
        self.check_range(temp_C)
        self._T = temp_C

    def is_enabled(self):
        return True

    def enable(self):
        pass

    def disable(self):
        input("Disable the TTC001 output (press ENTER on it so the display flashes), then press Enter here... ")

    def current_limit_A(self):
        return None

    def go_to(self, temp_C: float, *args, **kwargs) -> float:
        self.check_range(temp_C)
        input(f"Set the TTC001 to {self.describe(temp_C)}, enable it, wait until it holds steady, "
              "then press Enter... ")
        self._T = temp_C
        return temp_C


class SimTEC(_TECBase):
    """First-order thermal response, sped up so a simulated campaign runs quickly."""

    def __init__(self, tau_s: float = 0.5, **kw):
        super().__init__(**kw)
        self.tau_s = tau_s
        self._T = 25.0
        self._set = 25.0
        self._t = time.time()
        self._enabled = False

    def _advance(self):
        now = time.time()
        if self._enabled:
            import math
            self._T = self._set + (self._T - self._set) * math.exp(-(now - self._t) / self.tau_s)
        self._t = now

    def connect(self):
        pass

    def close(self):
        pass

    def read_C(self):
        self._advance()
        return self._T

    def set_C(self, temp_C):
        self.check_range(temp_C)
        self._advance()
        self._set = temp_C

    def setpoint_C(self):
        return self._set

    def tec_current_A(self):
        """Proportional drive clipped at 0.5 A (positive = heating), for the diagnostics."""
        if not self._enabled:
            return 0.0
        return max(-0.5, min(0.5, 0.3 * (self._set - self.read_C())))

    def is_enabled(self):
        return self._enabled

    def enable(self):
        self._advance()
        self._enabled = True

    def disable(self):
        self._advance()
        self._enabled = False

    def current_limit_A(self):
        return 0.5

    def go_to(self, temp_C, tol_C=0.05, hold_s=30.0, timeout_s=900.0, ramp_C_per_min=None, average_s=0.0):
        return super().go_to(temp_C, tol_C, min(hold_s, 0.3), timeout_s, ramp_C_per_min=None,
                             average_s=min(average_s, 0.3))

    def wait_until_stable(self, target_C, tol_C=0.05, hold_s=30.0, timeout_s=900.0, diverge_s=120.0, poll_s=1.0,
                          average_s=0.0):
        return super().wait_until_stable(target_C, tol_C, min(hold_s, 0.3), timeout_s, min(diverge_s, 2.0),
                                         poll_s=0.05, average_s=min(average_s, 0.3))


def open_tec(cfg: dict, mode: str):
    """mode: 'auto' (TTC001), 'manual' (front panel) or 'sim'."""
    t = cfg.get("tec", {})
    kw = dict(sensor=t.get("sensor", "TH20kOhm"), r25_kohm=float(t.get("r25_kohm", 10.0)),
              beta_K=float(t.get("beta_K", 3950.0)), min_C=float(t.get("min_C", 15.0)),
              max_C=float(t.get("max_C", 35.0)))
    if mode == "sim":
        return SimTEC(**kw)
    if mode == "manual":
        return ManualTEC(**kw)
    if mode == "auto":
        return TTC001(t.get("serial", ""), cfg["driver"]["kinesis_path"], **kw)
    raise ValueError(f"Unknown TEC mode {mode}")
