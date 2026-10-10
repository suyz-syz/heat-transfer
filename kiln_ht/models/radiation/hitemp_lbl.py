"""Line-by-line (LBL) spectral reference engine for imported HITEMP line lists.

This module does not bundle HITEMP data. Supply a licensed/user-obtained line-list
CSV using the documented schema. The line profile is a pseudo-Voigt approximation;
for metrology-grade reference results replace it with a validated Voigt/HTP engine.
Units: wavenumber cm-1, line strength cm-1/(molecule cm-2), pressure atm.
"""
from __future__ import annotations

from dataclasses import dataclass
import csv
import math
from pathlib import Path
from typing import Iterable, Sequence

C2_CM_K = 1.438776877  # second radiation constant, cm K
T_REF = 296.0
K_B = 1.380649e-23
C2_SI = 1.986445857e-23  # h*c in J cm
SIGMA_SB = 5.670374419e-8


@dataclass(frozen=True)
class SpectralLine:
    molecule: str
    nu: float
    strength_ref: float
    lower_energy: float
    air_gamma: float
    self_gamma: float = 0.0
    temp_exponent: float = 0.7
    partition_ref: float = 1.0
    partition_exponent: float = 0.0
    isotope: str = ""

    def __post_init__(self):
        vals = (self.nu, self.strength_ref, self.lower_energy, self.air_gamma,
                self.self_gamma, self.temp_exponent, self.partition_ref,
                self.partition_exponent)
        if not all(math.isfinite(v) for v in vals):
            raise ValueError("spectral line fields must be finite")
        if self.nu <= 0 or self.strength_ref < 0 or self.air_gamma < 0 or self.self_gamma < 0:
            raise ValueError("invalid spectral line frequency, strength, or broadening")
        if self.partition_ref <= 0:
            raise ValueError("partition_ref must be positive")


def load_hitemp_csv(path: str | Path) -> list[SpectralLine]:
    """Load normalized CSV columns: molecule,nu,strength_ref,lower_energy,
    air_gamma,self_gamma,temp_exponent,partition_ref,partition_exponent.
    HITEMP exports must be converted to these units/columns explicitly.
    """
    required = {f.name for f in SpectralLine.__dataclass_fields__.values()} - {"isotope"}
    lines = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"line-list CSV missing columns: {sorted(missing)}")
        for row in reader:
            lines.append(SpectralLine(
                molecule=row["molecule"].strip().upper(),
                nu=float(row["nu"]), strength_ref=float(row["strength_ref"]),
                lower_energy=float(row["lower_energy"]), air_gamma=float(row["air_gamma"]),
                self_gamma=float(row["self_gamma"] or 0.0),
                temp_exponent=float(row["temp_exponent"]),
                partition_ref=float(row["partition_ref"]),
                partition_exponent=float(row["partition_exponent"]),
                isotope=(row.get("isotope") or "").strip(),
            ))
    if not lines:
        raise ValueError("line-list CSV contains no spectral lines")
    return lines


def _partition_ratio(
    line: SpectralLine, temperature: float,
    partition_sums: dict[str, Sequence[tuple[float, float]]] | None,
) -> float:
    """Return Q(Tref)/Q(T); log-log interpolate validated TIPS tabulations.

    Keys are "MOLECULE:isotope" (for example "CO2:1") when isotope is present,
    otherwise molecule names. Tables must cover both Tref and requested T;
    extrapolation is deliberately rejected.
    """
    if partition_sums is None:
        return (T_REF / temperature) ** line.partition_exponent
    key = f"{line.molecule.upper()}:{line.isotope}" if line.isotope else line.molecule.upper()
    table = partition_sums.get(key)
    if not table or len(table) < 2:
        raise ValueError(f"missing partition-sum table with >=2 points for {key}")
    points = sorted((float(t), float(q)) for t, q in table)
    if any(not math.isfinite(t) or not math.isfinite(q) or t <= 0 or q <= 0 for t, q in points):
        raise ValueError(f"invalid partition-sum table for {key}")
    if any(points[i][0] == points[i-1][0] for i in range(1, len(points))):
        raise ValueError(f"duplicate temperatures in partition-sum table for {key}")

    def interpolate_q(t: float) -> float:
        if t < points[0][0] or t > points[-1][0]:
            raise ValueError(f"partition-sum table for {key} does not cover {t:g} K")
        for (t0, q0), (t1, q1) in zip(points, points[1:]):
            if t0 <= t <= t1:
                if t == t0:
                    return q0
                if t == t1:
                    return q1
                fraction = math.log(t / t0) / math.log(t1 / t0)
                return math.exp(math.log(q0) + fraction * math.log(q1 / q0))
        return points[-1][1]

    return interpolate_q(T_REF) / interpolate_q(temperature)


def line_strength(
    line: SpectralLine, temperature: float,
    partition_sums: dict[str, Sequence[tuple[float, float]]] | None = None,
) -> float:
    """Temperature-scaled line strength using TIPS tables when supplied.

    Without partition_sums, partition_exponent is a documented power-law
    approximation and must not be treated as a validated HITEMP/TIPS result.
    """
    if not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("temperature must be finite and positive")
    q_ratio = _partition_ratio(line, temperature, partition_sums)
    boltzmann = math.exp(-C2_CM_K * line.lower_energy * (1.0 / temperature - 1.0 / T_REF))
    stim_ref = -math.expm1(-C2_CM_K * line.nu / T_REF)
    stim_t = -math.expm1(-C2_CM_K * line.nu / temperature)
    return line.strength_ref * q_ratio * boltzmann * stim_t / stim_ref


def _pseudo_voigt(x: float, gaussian_sigma: float, lorentz_gamma: float) -> float:
    """Unit-area pseudo-Voigt profile (Olivero-Longbothum FWHM approximation)."""
    f_g = 2.0 * math.sqrt(2.0 * math.log(2.0)) * gaussian_sigma
    f_l = 2.0 * lorentz_gamma
    f = (f_g**5 + 2.69269*f_g**4*f_l + 2.42843*f_g**3*f_l**2
         + 4.47163*f_g**2*f_l**3 + 0.07842*f_g*f_l**4) ** 0.2 if f_g + f_l else 0.0
    if f <= 0:
        return 0.0
    ratio = f_l / f
    eta = max(0.0, min(1.0, 1.36603*ratio - 0.47719*ratio**2 + 0.11116*ratio**3))
    g = math.sqrt(4.0*math.log(2.0)/math.pi) / f * math.exp(-4.0*math.log(2.0)*(x/f)**2)
    l = (f / (2.0*math.pi)) / (x*x + (f/2.0)**2)
    return eta*l + (1.0-eta)*g


def absorption_spectrum(
    lines: Sequence[SpectralLine], wavenumbers: Sequence[float], temperature: float,
    pressure_atm: float, mole_fractions: dict[str, float], path_length_m: float,
    *, molar_masses_g_mol: dict[str, float] | None = None,
    partition_sums: dict[str, Sequence[tuple[float, float]]] | None = None,
) -> list[float]:
    """Return spectral absorption coefficient in 1/m on a supplied cm-1 grid.

    Pressure broadening is air/self weighted; the input composition is by mole.
    Doppler width uses species molar mass; CO2/H2O masses are supplied by default.
    """
    if temperature <= 0 or pressure_atm < 0 or path_length_m < 0:
        raise ValueError("temperature must be >0; pressure/path length must be nonnegative")
    masses = {"CO2": 44.0095, "H2O": 18.01528, "N2": 28.0134, "O2": 31.9988}
    if molar_masses_g_mol:
        masses.update({k.upper(): v for k, v in molar_masses_g_mol.items()})
    result = [0.0] * len(wavenumbers)
    for line in lines:
        xmol = mole_fractions.get(line.molecule.upper(), 0.0)
        if xmol <= 0:
            continue
        mass = masses.get(line.molecule.upper())
        if mass is None or mass <= 0:
            raise ValueError(f"missing positive molar mass for {line.molecule}")
        nu0 = line.nu
        gamma = pressure_atm * (T_REF / temperature) ** line.temp_exponent * (
            line.air_gamma * max(0.0, 1.0-xmol) + line.self_gamma*xmol)
        mass_kg = mass / 1000.0 / 6.02214076e23
        sigma_d = nu0 * math.sqrt(K_B*temperature/(mass_kg*299792458.0**2))
        strength = line_strength(line, temperature, partition_sums)
        # Integrated line strength in cm/molecule -> m2/molecule after cm^-1 conversion.
        # Number density is ideal-gas molecular number density; final coefficient is 1/m.
        number_density = xmol * pressure_atm * 101325.0 / (K_B*temperature)
        for i, nu in enumerate(wavenumbers):
            profile = _pseudo_voigt(nu-nu0, sigma_d, gamma)
            # S has units cm/molecule and profile has units cm, so S*profile
            # is cm^2/molecule. Convert the cross-section to m^2 (1e-4), then
            # multiply by number density in molecules/m^3 to obtain 1/m.
            result[i] += strength * profile * number_density * 1e-4
    return result


def gas_emissivity_from_spectrum(
    absorption: Sequence[float], wavenumbers: Sequence[float], temperature: float,
    path_length_m: float,
) -> float:
    """Planck-weighted total emissivity from spectral transmittance (uniform slab)."""
    if len(absorption) != len(wavenumbers) or len(absorption) < 2:
        raise ValueError("absorption and wavenumber grids must have equal length >= 2")
    if temperature <= 0 or path_length_m < 0:
        raise ValueError("invalid temperature or path length")
    weighted_abs, weighted_planck = 0.0, 0.0
    # Planck spectral exitance per wavenumber; constants cancel in the ratio.
    for i in range(len(wavenumbers)-1):
        # Use wavenumber in cm^-1 with C2 in cm K. The factor 100 belongs
        # only in the SI spectral-flux routine below; applying it here
        # suppresses Planck weights by exp(-O(100)) and corrupts emissivity.
        nu_cm = 0.5 * (wavenumbers[i] + wavenumbers[i+1])
        if nu_cm <= 0:
            continue
        z = C2_CM_K * nu_cm / temperature
        if z > 700:
            continue
        planck = nu_cm**3 / math.expm1(z)
        a = 1.0 - math.exp(-max(0.0, 0.5*(absorption[i]+absorption[i+1]))*path_length_m)
        dnu = abs(wavenumbers[i+1]-wavenumbers[i])
        weighted_abs += planck*a*dnu
        weighted_planck += planck*dnu
    if weighted_planck <= 0:
        raise ValueError("wavenumber grid has no positive Planck weight")
    return min(1.0, max(0.0, weighted_abs/weighted_planck))



def spectral_net_radiative_flux(
    absorption_coefficients_m_inv: Sequence[float],
    wavenumbers_cm_inv: Sequence[float],
    gas_temperature_K: float,
    wall_temperature_K: float,
    path_length_m: float,
    wall_emissivity: float = 1.0,
) -> float:
    """Net gas-to-wall radiative heat flux [W/m2] over the supplied band.

    Assumes a uniform, isothermal, non-scattering slab and an opaque gray wall.
    Spectral exchange factor is eps_g*eps_w/(eps_g+eps_w-eps_g*eps_w).
    The returned flux covers only the supplied wavenumber interval; a total-flux
    benchmark requires a sufficiently broad grid and a grid-convergence check.
    """
    n = len(wavenumbers_cm_inv)
    if n < 2 or len(absorption_coefficients_m_inv) != n:
        raise ValueError("absorption and wavenumber arrays must have equal length >= 2")
    if (not math.isfinite(gas_temperature_K) or not math.isfinite(wall_temperature_K)
            or gas_temperature_K <= 0 or wall_temperature_K <= 0
            or not math.isfinite(path_length_m) or path_length_m < 0):
        raise ValueError("temperatures must be positive and path length nonnegative")
    if not math.isfinite(wall_emissivity) or not 0 < wall_emissivity <= 1:
        raise ValueError("wall_emissivity must be in (0, 1]")
    if any(not math.isfinite(x) or x < 0 for x in absorption_coefficients_m_inv):
        raise ValueError("absorption coefficients must be finite and nonnegative")
    if any(not math.isfinite(x) or x < 0 for x in wavenumbers_cm_inv):
        raise ValueError("wavenumbers must be finite and nonnegative")

    h = 6.62607015e-34
    c = 299792458.0
    k_b = 1.380649e-23

    def planck_exitance(nu_m_inv: float, temp: float) -> float:
        if nu_m_inv <= 0:
            return 0.0
        z = h * c * nu_m_inv / (k_b * temp)
        if z > 700:
            return 0.0
        return 2.0 * math.pi * h * c*c * nu_m_inv**3 / math.expm1(z)

    total = 0.0
    for i in range(n - 1):
        nu_cm = 0.5 * (wavenumbers_cm_inv[i] + wavenumbers_cm_inv[i+1])
        nu_m = 100.0 * nu_cm
        delta_nu_m = 100.0 * abs(wavenumbers_cm_inv[i+1] - wavenumbers_cm_inv[i])
        alpha = 0.5 * (absorption_coefficients_m_inv[i] + absorption_coefficients_m_inv[i+1])
        eps_g = -math.expm1(-alpha * path_length_m)
        denom = eps_g + wall_emissivity - eps_g * wall_emissivity
        eps_exchange = eps_g * wall_emissivity / denom if denom > 0 else 0.0
        total += eps_exchange * (
            planck_exitance(nu_m, gas_temperature_K)
            - planck_exitance(nu_m, wall_temperature_K)
        ) * delta_nu_m
    return total
