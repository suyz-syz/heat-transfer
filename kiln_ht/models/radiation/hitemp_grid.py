"""Offline HITEMP narrow-spectrum lookup model.

This opt-in model integrates the committed 1025--3975 cm-1 band only. It is an
experimental, band-limited model and must not be interpreted as total-spectrum
radiation. The tabulated alpha_nu is linearly interpolated over T, P and the
triangulated CO2/H2O composition hull; optical path is evaluated analytically.
No extrapolation is permitted.
"""
from __future__ import annotations

import array
import csv
from functools import lru_cache
import hashlib
import json
import math
import os
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

C2_CM_K = 1.438776877
_LOAD_LOCK = RLock()
_GRID = None


@dataclass(frozen=True)
class HitempGridResult:
    emissivity: float
    absorptivity: float
    kappa_eff: float
    optical_thickness: float
    path_length: float
    model_name: str = "hitemp_grid"


@dataclass(frozen=True)
class _Grid:
    temperatures: tuple[float, ...]
    pressures: tuple[float, ...]
    compositions: tuple[tuple[str, float, float], ...]
    wavenumbers: tuple[float, ...]
    paths: tuple[float, ...]
    spectra: dict[tuple[int, int, int], array.array]
    composition_triangles: tuple[tuple[int, int, int], ...]


def _data_dir() -> Path:
    configured = os.environ.get("KILN_HT_HITEMP_GRID_PATH")
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_dir() else path.parent
    return Path(__file__).resolve().parents[3] / "data"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_grid() -> _Grid:
    global _GRID
    if _GRID is not None:
        return _GRID
    with _LOAD_LOCK:
        if _GRID is not None:
            return _GRID
        root = _data_dir()
        manifest_path = root / "manifest.json"
        if not manifest_path.is_file():
            raise RuntimeError(
                f"hitemp_grid manifest.json is unavailable under {root}"
            )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            metadata = manifest["spectral_grid"]
            domain = metadata["spectral_grid_cm-1"]
            temperatures = tuple(float(x) for x in metadata["temperature_K"])
            pressures = tuple(float(x) for x in metadata["pressure_atm"])
            compositions = tuple((str(x["name"]), float(x["x_co2"]), float(x["x_h2o"]))
                                 for x in metadata["compositions"])
            paths = tuple(float(x) for x in metadata["path_m"])
            expected_sha = metadata["output_sha256"]
            expected_points = int(domain["points"])
            nu_min, nu_max, nu_step = (float(domain[k]) for k in ("min", "max", "step"))
            triangles = tuple(tuple(int(i) for i in tri)
                              for tri in metadata["composition_triangles"])
            compact = metadata.get("compact_binary")
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"invalid HITEMP spectral grid manifest {manifest_path}") from exc
        if (len(temperatures) < 2 or len(pressures) < 2 or len(compositions) < 3
                or not math.isclose(nu_min + (expected_points - 1) * nu_step, nu_max, abs_tol=1e-8)
                or any(b <= a for a, b in zip(temperatures, temperatures[1:]))
                or any(b <= a for a, b in zip(pressures, pressures[1:]))
                or any(p <= 0 for p in paths)):
            raise RuntimeError("HITEMP grid dimensions or axes are invalid")
        t_index = {v: i for i, v in enumerate(temperatures)}
        p_index = {v: i for i, v in enumerate(pressures)}
        c_index = {name: i for i, (name, _, _) in enumerate(compositions)}
        spectra = {(it, ip, ic): array.array("f" if compact else "d")
                   for it in range(len(temperatures))
                   for ip in range(len(pressures))
                   for ic in range(len(compositions))}
        wavenumbers = tuple(nu_min + i * nu_step for i in range(expected_points))
        compact_path = root / str(compact.get("file", "")) if compact else None
        expected_shape = [len(temperatures), len(pressures), len(compositions), expected_points]
        if compact is not None:
            if compact_path is None or not compact_path.is_file():
                raise RuntimeError("manifest requires a compact HITEMP grid, but its file is missing")
            if compact.get("format") != "HITGRD01" or compact.get("dtype") != "<f4":
                raise RuntimeError("unsupported compact HITEMP grid format")
            if (compact.get("shape") != expected_shape
                    or compact.get("uncompressed_bytes") != math.prod(expected_shape) * 4
                    or compact.get("source_csv_sha256") != expected_sha
                    or compact.get("compression") != "zlib"):
                raise RuntimeError("compact HITEMP manifest dimensions or source metadata are invalid")
            if compact_path.stat().st_size != compact.get("bytes"):
                raise RuntimeError("compact HITEMP grid byte count does not match manifest")
            if _sha256(compact_path) != compact.get("sha256"):
                raise RuntimeError("compact HITEMP grid SHA-256 does not match manifest")
            try:
                blob = compact_path.read_bytes()
                if blob[:8] != b"HITGRD01" or len(blob) < 12:
                    raise ValueError("bad magic or truncated header")
                header_size = struct.unpack("<I", blob[8:12])[0]
                header_end = 12 + header_size
                if header_end > len(blob):
                    raise ValueError("truncated header")
                header = json.loads(blob[12:header_end].decode("utf-8"))
                if (header.get("dtype") != "<f4" or header.get("shape") != expected_shape
                        or header.get("order") != "C" or header.get("compression") != "zlib"
                        or header.get("source_csv_sha256") != expected_sha
                        or header.get("uncompressed_bytes") != math.prod(expected_shape) * 4):
                    raise ValueError("header does not match manifest grid")
                raw = zlib.decompress(blob[header_end:])
                if len(raw) != header["uncompressed_bytes"]:
                    raise ValueError("payload byte count mismatch")
                flat = array.array("f")
                flat.frombytes(raw)
                if sys.byteorder != "little":
                    flat.byteswap()
                if len(flat) != math.prod(expected_shape) or any(not math.isfinite(v) or v < 0 for v in flat):
                    raise ValueError("invalid alpha payload")
                offset = 0
                for key in spectra:
                    spectra[key] = array.array("f", flat[offset:offset + expected_points])
                    offset += expected_points
            except (ValueError, KeyError, TypeError, zlib.error, struct.error) as exc:
                raise RuntimeError(f"invalid compact HITEMP grid {compact_path}: {exc}") from exc
        else:
            csv_path = root / "spectral_grid_alpha_tau.csv"
            if not csv_path.is_file():
                raise RuntimeError("HITEMP spectral grid files are unavailable (compact binary and CSV missing)")
            if _sha256(csv_path) != expected_sha:
                raise RuntimeError("HITEMP spectral grid SHA-256 does not match manifest")
            previous_key = None
            with csv_path.open("r", newline="", encoding="utf-8-sig") as stream:
                reader = csv.DictReader(stream)
                required = {"temperature_K", "pressure_atm", "composition", "x_co2", "x_h2o",
                            "wavenumber_cm-1", "alpha_m-1"}
                if not required.issubset(reader.fieldnames or []):
                    raise RuntimeError("HITEMP spectral CSV is missing required columns")
                for row in reader:
                    try:
                        temp, pressure = float(row["temperature_K"]), float(row["pressure_atm"])
                        name = row["composition"]
                        ic = c_index[name]
                        it, ip = t_index[temp], p_index[pressure]
                        x_co2, x_h2o = float(row["x_co2"]), float(row["x_h2o"])
                        nu, alpha = float(row["wavenumber_cm-1"]), float(row["alpha_m-1"])
                    except (KeyError, ValueError, TypeError) as exc:
                        raise RuntimeError("invalid row in HITEMP spectral CSV") from exc
                    _, expected_co2, expected_h2o = compositions[ic]
                    if (abs(x_co2 - expected_co2) > 1e-12 or abs(x_h2o - expected_h2o) > 1e-12
                            or alpha < 0 or not all(math.isfinite(v) for v in
                                                    (temp, pressure, x_co2, x_h2o, nu, alpha))):
                        raise RuntimeError("invalid composition or absorption value in HITEMP grid")
                    key = (it, ip, ic)
                    if key != previous_key:
                        expected_idx = 0
                        if len(spectra[key]) != 0:
                            raise RuntimeError("duplicate or non-contiguous HITEMP spectra in CSV")
                        previous_key = key
                    else:
                        expected_idx = len(spectra[key])
                    expected_nu = nu_min + expected_idx * nu_step
                    if not math.isclose(nu, expected_nu, rel_tol=0.0, abs_tol=2e-7):
                        raise RuntimeError("HITEMP spectral CSV wavenumber grid is incomplete or unordered")
                    spectra[key].append(alpha)
        if any(len(values) != expected_points for values in spectra.values()):
            raise RuntimeError("one or more HITEMP condition spectra have the wrong point count")
        _GRID = _Grid(temperatures, pressures, compositions, wavenumbers, paths, spectra, triangles)
        return _GRID


def _bracket(axis: tuple[float, ...], value: float, label: str) -> tuple[int, int, float]:
    if not math.isfinite(value) or value < axis[0] or value > axis[-1]:
        raise ValueError(f"{label}={value!r} outside HITEMP calibration domain [{axis[0]}, {axis[-1]}]")
    if value == axis[-1]:
        return len(axis) - 2, len(axis) - 1, 1.0
    lo = 0
    while lo + 1 < len(axis) and axis[lo + 1] < value:
        lo += 1
    fraction = (value - axis[lo]) / (axis[lo + 1] - axis[lo])
    return lo, lo + 1, fraction


def _composition_weights(grid: _Grid, x_co2: float, x_h2o: float):
    if (not math.isfinite(x_co2) or not math.isfinite(x_h2o) or x_co2 < 0 or x_h2o < 0
            or x_co2 + x_h2o > 1.0 + 1e-12):
        raise ValueError("CO2/H2O mole fractions are invalid")
    for triangle in grid.composition_triangles:
        ia, ib, ic = triangle
        _, ax, ay = grid.compositions[ia]
        _, bx, by = grid.compositions[ib]
        _, cx, cy = grid.compositions[ic]
        v0x, v0y, v1x, v1y = bx - ax, by - ay, cx - ax, cy - ay
        det = v0x * v1y - v1x * v0y
        if abs(det) < 1e-18:
            continue
        dx, dy = x_co2 - ax, x_h2o - ay
        wb = (dx * v1y - v1x * dy) / det
        wc = (v0x * dy - dx * v0y) / det
        wa = 1.0 - wb - wc
        if min(wa, wb, wc) >= -1e-10 and max(wa, wb, wc) <= 1.0 + 1e-10:
            return ((ia, max(0.0, wa)), (ib, max(0.0, wb)), (ic, max(0.0, wc)))
    raise ValueError("CO2/H2O composition lies outside the calibrated composition hull")


def _interpolate_spectrum(grid: _Grid, temperature: float, pressure_atm: float,
                          x_co2: float, x_h2o: float) -> list[float]:
    t0, t1, wt = _bracket(grid.temperatures, temperature, "temperature_K")
    p0, p1, wp = _bracket(grid.pressures, pressure_atm, "pressure_atm")
    c_weights = _composition_weights(grid, x_co2, x_h2o)
    coefficients = {}
    for it, tw in ((t0, 1.0 - wt), (t1, wt)):
        for ip, pw in ((p0, 1.0 - wp), (p1, wp)):
            for ic, cw in c_weights:
                key = (it, ip, ic)
                coefficients[key] = coefficients.get(key, 0.0) + tw * pw * cw
    result = [0.0] * len(grid.wavenumbers)
    for key, coefficient in coefficients.items():
        if coefficient == 0.0:
            continue
        spectrum = grid.spectra[key]
        for i, alpha in enumerate(spectrum):
            result[i] += coefficient * alpha
    return result


@lru_cache(maxsize=64)
def _cached_spectrum(temperature: float, pressure_atm: float,
                     x_co2: float, x_h2o: float) -> tuple[float, ...]:
    grid = _load_grid()
    return tuple(_interpolate_spectrum(grid, temperature, pressure_atm, x_co2, x_h2o))


def _band_emissivity(grid: _Grid, alpha: list[float], temperature: float, path_length: float) -> float:
    nu = grid.wavenumbers
    step = nu[1] - nu[0]
    weighted = []
    for wn, coeff in zip(nu, alpha):
        z = C2_CM_K * wn / temperature
        planck_shape = 0.0 if z > 700.0 else wn**3 / math.expm1(z)
        absorptance = -math.expm1(-coeff * path_length)
        weighted.append(planck_shape * absorptance)
    band_integral = step * (0.5 * weighted[0] + sum(weighted[1:-1]) + 0.5 * weighted[-1])
    total_planck_integral = (math.pi**4 / 15.0) * (temperature / C2_CM_K) ** 4
    value = band_integral / total_planck_integral
    if not math.isfinite(value) or value < -1e-12 or value > 1.0 + 1e-8:
        raise RuntimeError("interpolated HITEMP band emissivity violates physical bounds")
    return min(1.0, max(0.0, value))


@lru_cache(maxsize=512)
def _emissivity_cached(temperature: float, pressure_atm: float,
                       x_co2: float, x_h2o: float, path_length: float) -> float:
    grid = _load_grid()
    alpha = _cached_spectrum(temperature, pressure_atm, x_co2, x_h2o)
    return _band_emissivity(grid, alpha, temperature, path_length)


@lru_cache(maxsize=2048)
def _absorptivity_cached(gas_temperature: float, wall_temperature: float,
                         pressure_atm: float, x_co2: float, x_h2o: float,
                         path_length: float) -> float:
    grid = _load_grid()
    alpha = _cached_spectrum(gas_temperature, pressure_atm, x_co2, x_h2o)
    return _band_emissivity(grid, alpha, wall_temperature, path_length)


def evaluate(T_gas: float, T_wall: float, pCO2: float, pH2O: float, L: float,
             eps_wall: float = 0.85, *, total_pressure_atm: float | None = None,
             x_co2: float | None = None, x_h2o: float | None = None) -> HitempGridResult:
    """Return band-limited gas emissivity/absorptivity for the gray-wall closure.

    Partial pressures are accepted in Pa for API consistency. The total pressure
    in atm and mole fractions are also required to locate the calibrated grid.
    """
    if total_pressure_atm is None or x_co2 is None or x_h2o is None:
        raise ValueError("hitemp_grid requires total_pressure_atm, x_co2, and x_h2o")
    if (not all(math.isfinite(v) for v in
                (T_gas, T_wall, pCO2, pH2O, L, eps_wall, total_pressure_atm, x_co2, x_h2o))
            or T_gas <= 0 or T_wall <= 0 or pCO2 < 0 or pH2O < 0 or L <= 0
            or not 0.7 < eps_wall <= 1.0):
        raise ValueError("invalid HITEMP radiation input")
    if not (0.1 <= L <= 5.0):
        raise ValueError("path length outside HITEMP calibration domain [0.1, 5.0] m")
    expected_total_pa = total_pressure_atm * 101325.0
    if (abs(pCO2 - x_co2 * expected_total_pa) > max(1e-5, expected_total_pa * 1e-8)
            or abs(pH2O - x_h2o * expected_total_pa) > max(1e-5, expected_total_pa * 1e-8)):
        raise ValueError("partial pressures, total pressure, and mole fractions are inconsistent")
    grid = _load_grid()
    if len(grid.wavenumbers) < 2:
        raise RuntimeError("HITEMP grid needs at least two spectral points")
    emissivity = _emissivity_cached(T_gas, total_pressure_atm, x_co2, x_h2o, L)
    absorptivity = _absorptivity_cached(
        T_gas, T_wall, total_pressure_atm, x_co2, x_h2o, L)
    optical_thickness = -math.log1p(-emissivity) if emissivity < 1.0 else 700.0
    return HitempGridResult(emissivity, absorptivity, optical_thickness / L,
                            optical_thickness, L)
