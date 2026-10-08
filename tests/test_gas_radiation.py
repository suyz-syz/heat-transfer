# -*- coding: utf-8 -*-
import math
import pytest

from kiln_ht import GasMixture, get_gas_properties, get_gas_radiation, KilnParams, Layer, solve_wall
from kiln_ht.models.properties.nasa import species_properties

SPECIES = ("CO2", "H2O", "N2", "O2")

def test_mole_and_mass_fraction_roundtrip():
    y = GasMixture.from_mole_fractions({"CO2":0.18,"H2O":0.10,"N2":0.68,"O2":0.04})
    M = y.molecular_weight()
    ws = {s:y.as_dict()[s] * {"CO2":44.0095e-3,"H2O":18.01528e-3,"N2":28.0134e-3,"O2":31.9988e-3}[s] / M for s in SPECIES}
    z = GasMixture.from_mass_fractions(ws)
    for s in SPECIES:
        assert z.as_dict()[s] == pytest.approx(y.as_dict()[s], rel=1e-12)

@pytest.mark.parametrize("T", [300.0, 400.0, 600.0, 1000.0, 1500.0, 2000.0])
def test_species_properties_finite_positive(T):
    for s in SPECIES:
        p = species_properties(s, T)
        assert all(math.isfinite(x) and x > 0 for x in (p.cp,p.mu,p.k))

@pytest.mark.parametrize("T", [300.0, 500.0, 800.0, 1200.0, 1600.0, 2000.0])
def test_mixture_property_chain_no_divergence(T):
    gas = GasMixture.from_mole_fractions({"CO2":0.18,"H2O":0.10,"N2":0.68,"O2":0.04})
    p = get_gas_properties(T, 101325.0, gas)
    assert all(math.isfinite(x) and x > 0 for x in (p.rho,p.cp,p.mu,p.k,p.Pr,p.M,p.R))
    assert p.Pr < 10.0

@pytest.mark.parametrize("T", [300.0, 500.0, 800.0, 1200.0, 1600.0, 2000.0])
@pytest.mark.parametrize("model", ["leckner","wsgg"])
def test_radiation_chain_300_2000K(T, model):
    r = get_gas_radiation(T, max(300.0, 0.75*T), 0.18*101325.0, 0.10*101325.0, 3.8, model=model)
    assert all(math.isfinite(x) for x in (r.emissivity,r.absorptivity,r.kappa_eff,r.optical_thickness,r.q_rad,r.h_rad))
    assert 0.0 <= r.emissivity <= 1.0
    assert 0.0 <= r.absorptivity <= 1.0
    assert r.kappa_eff >= 0.0
    assert r.h_rad >= 0.0

def test_wsgg_and_leckner_are_distinguishable():
    a = get_gas_radiation(1523.15, 900.0, 0.20*101325.0, 0.08*101325.0, 3.8, model="leckner")
    b = get_gas_radiation(1523.15, 900.0, 0.20*101325.0, 0.08*101325.0, 3.8, model="wsgg")
    assert not math.isclose(a.q_rad, b.q_rad, rel_tol=1e-6)

def test_solve_wall_backward_compatible_default():
    layers=[Layer("fiber",0.15,k=0.10),Layer("shell",0.012,k=45.0)]
    sol=solve_wall(layers,KilnParams())
    assert math.isfinite(sol.Qprime) and sol.Qprime > 0
    assert 0.0 <= sol.eg <= 1.0
