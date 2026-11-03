"""Thorlabs CCS compact spectrometer (CCS100/125/150/175/200) through the TLCCS driver.

Install ThorSpectra from Thorlabs: it puts TLCCS_64.dll in C:\\Program Files\\IVI Foundation\\VISA\\Win64\\Bin
and registers the spectrometer with NI-VISA as a RAW USB resource, e.g.
USB0::0x1313::0x8087::M00766231::RAW. Close ThorSpectra before running scripts.

Calls follow Thorlabs' "CCS using ctypes - Python 3" example (Light_Analysis_Examples):
tlccs_init, tlccs_setIntegrationTime, tlccs_getWavelengthData, tlccs_startScan,
tlccs_getDeviceStatus (bit 0x10 = scan data ready), tlccs_getScanData (3648 pixels), tlccs_close.

The CCS175 resolves ~0.6-1 nm, so it cannot separate FP modes 0.1 nm apart or measure SMSR, but a
fit to a single laser line finds its centre to a few pm: enough for current and temperature tuning.
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from pathlib import Path

import numpy as np

N_PIXELS = 3648
DLL_DIR = r"C:\Program Files\IVI Foundation\VISA\Win64\Bin"
STATUS_SCAN_READY = 0x0010


class CCSError(RuntimeError):
    pass


def find_ccs(serial: str = "") -> str:
    import pyvisa
    rm = pyvisa.ResourceManager()
    try:
        found = [r for r in rm.list_resources("USB?*::RAW") if "0x1313" in r.lower()]
    finally:
        rm.close()
    if serial:
        found = [r for r in found if serial in r]
    if not found:
        raise CCSError("No Thorlabs CCS spectrometer found as a VISA RAW resource. Install ThorSpectra, plug it in "
                       "by USB, close ThorSpectra, and check VISA Interactive Control lists USB0::0x1313::...::RAW.")
    return found[0]


def peak_centre(wl, counts, frac: float = 0.5):
    """Centre of the strongest line: intensity-weighted centroid of the points above frac x peak,
    after removing the baseline. Returns (centre_nm, fwhm_nm, peak_counts)."""
    wl = np.asarray(wl, float)
    y = np.asarray(counts, float)
    y = y - np.median(y)
    k = int(np.argmax(y))
    top = y[k]
    if top <= 0:
        raise CCSError("No line in the spectrum (is the laser on and the fibre connected?)")
    lo = k
    while lo > 0 and y[lo - 1] > frac * top:
        lo -= 1
    hi = k
    while hi < len(y) - 1 and y[hi + 1] > frac * top:
        hi += 1
    lo, hi = max(lo - 1, 0), min(hi + 1, len(y) - 1)
    w = np.clip(y[lo:hi + 1] - frac * top, 0, None)
    centre = float(np.sum(wl[lo:hi + 1] * w) / np.sum(w)) if w.sum() > 0 else float(wl[k])
    above = np.where(y > 0.5 * top)[0]
    fwhm = float(wl[above[-1]] - wl[above[0]]) if len(above) > 1 else float(np.median(np.diff(wl)))
    return centre, fwhm, float(top)


class CCS:
    def __init__(self, resource: str = "", serial: str = "", integration_s: float = 1e-3, dll_dir: str = DLL_DIR):
        if sys.platform != "win32":
            raise CCSError("The TLCCS driver only runs on Windows. Use --mode sim elsewhere.")
        path = Path(dll_dir)
        if not (path / "TLCCS_64.dll").exists():
            raise CCSError(f"TLCCS_64.dll not found in {path}. Install ThorSpectra from Thorlabs.")
        os.add_dll_directory(str(path))
        self._lib = ctypes.cdll.LoadLibrary(str(path / "TLCCS_64.dll"))
        self.resource = resource or find_ccs(serial)
        self._h = ctypes.c_int(0)
        code = self._lib.tlccs_init(self.resource.encode(), 1, 1, ctypes.byref(self._h))
        if code != 0:
            raise CCSError(f"tlccs_init({self.resource}) failed with code {code}. Is ThorSpectra still open?")
        self.idn = f"Thorlabs CCS {self.resource}"
        self.integration_s = None
        self.set_integration(integration_s)
        wl = (ctypes.c_double * N_PIXELS)()
        self._lib.tlccs_getWavelengthData(self._h, 0, ctypes.byref(wl), ctypes.c_void_p(None), ctypes.c_void_p(None))
        self.wavelengths = np.array(wl[:], float)

    def set_integration(self, seconds: float):
        seconds = float(min(max(seconds, 1e-5), 60.0))
        code = self._lib.tlccs_setIntegrationTime(self._h, ctypes.c_double(seconds))
        if code != 0:
            raise CCSError(f"tlccs_setIntegrationTime failed with code {code}")
        self.integration_s = seconds

    def scan(self, timeout_s: float = 10.0) -> np.ndarray:
        self._lib.tlccs_startScan(self._h)
        status = ctypes.c_int(0)
        t0 = time.time()
        while (status.value & STATUS_SCAN_READY) == 0:
            self._lib.tlccs_getDeviceStatus(self._h, ctypes.byref(status))
            if time.time() - t0 > timeout_s + self.integration_s:
                raise CCSError("CCS scan timed out")
            time.sleep(0.002)
        data = (ctypes.c_double * N_PIXELS)()
        self._lib.tlccs_getScanData(self._h, ctypes.byref(data))
        return np.array(data[:], float)

    def close(self):
        try:
            self._lib.tlccs_close(self._h)
        except Exception:
            pass


class SimCCS:
    """A DBR line on a flat background, centred where the simulated laser says."""

    def __init__(self, laser=None, driver=None, integration_s: float = 1e-3, seed: int = 0):
        self.laser, self.driver = laser, driver
        self.wavelengths = np.linspace(500, 1000, N_PIXELS)
        self.integration_s = integration_s
        self.idn = "SIMULATED CCS175"
        self.rng = np.random.default_rng(seed)

    def set_integration(self, seconds):
        self.integration_s = float(min(max(seconds, 1e-5), 60.0))

    def scan(self, timeout_s=10.0):
        I = self.driver.actual_mA() if self.driver else 100.0
        centre = self.laser.wavelength_nm(I) if self.laser else 852.0
        P = self.laser.power_W(I) * 1000 if self.laser else 5.0
        height = min(1.0, 0.6 * P / 5.0 * self.integration_s / 1e-3)
        y = height * np.exp(-0.5 * ((self.wavelengths - centre) / 0.3) ** 2)
        return np.clip(y + self.rng.normal(0.002, 0.0015, N_PIXELS), 0, 1.0)

    def close(self):
        pass


def auto_scan(ccs, target=(0.3, 0.8), tries: int = 8, n_avg: int = 3):
    """Adjust the integration time until the line sits between 30 % and 80 % of full scale, then
    average n_avg scans. The CCS returns 0..1 (1 = saturated)."""
    y = ccs.scan()
    for _ in range(tries):
        top = float(np.max(y))
        if top >= 0.98:
            ccs.set_integration(ccs.integration_s / 4)
        elif top < target[0]:
            ccs.set_integration(ccs.integration_s * min(10.0, 0.55 / max(top, 1e-3)))
        elif top > target[1]:
            ccs.set_integration(ccs.integration_s * 0.55 / top)
        else:
            break
        y = ccs.scan()
    if np.max(y) >= 0.98:
        raise CCSError("Spectrometer saturated even at the shortest integration time: add attenuation.")
    return np.mean([y] + [ccs.scan() for _ in range(n_avg - 1)], axis=0)
