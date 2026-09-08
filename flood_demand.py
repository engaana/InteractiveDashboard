"""
flood_demand.py — ASCE/SEI 7-22 Supplement 2 flood demand for the MOGA engine.

Python port of the physics of the dashboard's "Flood Loads — Building Cross-Section" card
(flood_section_module.html) so that the NSGA-II engine (moga_flood_preservation.py) evaluates
exactly the same structural demand as the in-browser surrogate:

  hydrostatic   §5.4.2  Eq. 5.4-3, basement / unequal case per FEMA P-2345 Fig. 5B
                        F_w = ½·γw·z²,  F_dif = ½·(γs − γw)·h_b²
  hydrodynamic  §5.4.3.2 Eq. 5.4-5, Cd from Table 5.4-2 (B/d_f), d_f capped at the structure height
  debris impact §5.4.5  Eq. 5.4-20, F_di = Co·V·CR·Cs·√(k_e·m), series stiffness k_e with the URM panel,
                        required when d_f > 0.91 m (3 ft), CR = 1 for d_f ≥ 1.52 m (5 ft)

`FloodDemand.demand(he, wl, ep, s)` mirrors `window.FLOOD.demandAt(he, {wl, ep, s})` of the card:
the demand (kN on a wall panel of width `wl`) when the water head on the wall is `he` (m above grade),
with the load components selected in the card's Fa builder (`sel`). For the wet strategy (s = 2) the
basement water is NOT excluded (interior and exterior water equalise), as in the card.

The parameters are the card's own inputs, exported as `window.FLOOD.state.params` (SI units:
elevations in m, kN, kN/m³, GPa for Em) — see pilot_flood_params.json for the Old Labor Hall pilot.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Dict, Optional

FT = 0.3048
DEBRIS = {"log": (4.45, 61294.0), "veh": (10.68, 1051.0), "ves": (11.1, 5250.0)}   # W (kN), k (kN/m) — S2 Table 5.4-4


def cd_table(r_bd: float) -> float:
    """Table 5.4-2: Cd = 1.25 for B/d_f ≤ 12, 2.0 for ≥ 120, linear in between."""
    if r_bd <= 12:
        return 1.25
    if r_bd >= 120:
        return 2.0
    return 1.25 + (r_bd - 12) * (2.0 - 1.25) / (120 - 12)


def hydrostatic(SWEL: float, Ge: float, ELb: float, basement: bool, gs: float, gw: float) -> Dict[str, float]:
    d_f = max(SWEL - Ge, 0.0)
    d_h, h_b, F_dif, p_B, z = d_f, 0.0, 0.0, 0.0, 0.0
    if basement:
        z = max(SWEL - ELb, 0.0)
        h_b = max(Ge - ELb, 0.0)
        d_h = z
        F_dif = 0.5 * (gs - gw) * h_b * h_b
        p_B = gw * z
    F_w = 0.5 * gw * d_h * d_h
    F_sta = F_w + F_dif
    z_sta = (F_w * d_h / 3 + F_dif * h_b / 3) / F_sta if F_sta > 0 else 0.0
    return dict(d_f=d_f, z=z, h_b=h_b, d_h=d_h, F_w=F_w, F_dif=F_dif, F_sta=F_sta, z_sta=z_sta,
                p_base=gw * d_h + (gs - gw) * h_b, p_B=p_B)


def hydrodynamic(p: dict, d_f: float) -> Dict[str, float]:
    gw = p["GW"]
    rho = 1027.0 if gw > 10 else 1000.0
    Hs = p["FFE"] + p["n"] * p["hs"] - p["Ge"]
    d = min(d_f, max(Hs, 0.0))
    r_bd = p["B"] / d if d > 0 else math.inf
    Cd = cd_table(r_bd) if p.get("cdMode", "auto") == "auto" else p["Cd"]
    p_dyn = 0.5 * rho * Cd * p["V"] ** 2 / 1000.0          # kPa
    F_dyn = p_dyn * p["B"] * d                             # kN, whole face
    return dict(rho=rho, Hs=Hs, d=d, r_bd=r_bd, Cd=Cd, p_dyn=p_dyn, F_dyn=F_dyn,
                f_dyn=F_dyn / p["B"] if p["B"] > 0 else 0.0, z_dyn=d / 2)


def debris(p: dict, d_f: float) -> Dict[str, float]:
    g = 9.81
    req = d_f > 0.91
    CR = 1.0 if d_f >= 1.52 else (0.0 if d_f < 0.30 else (d_f - 0.30) / (1.52 - 0.30))
    Cs = 1.0 if p.get("csMode", "lb") == "lb" else p["Cs"]
    Wd, kd = p["Wd"], p["kd"]
    if p.get("deb", "custom") in DEBRIS:
        Wd, kd = DEBRIS[p["deb"]]
    I = p["be"] * p["tw"] ** 3 / 12.0
    k_panel = p["Kbc"] * (p["Em"] * 1e6) * I / p["Lp"] ** 3           # kN/m
    k_e = 1.0 / (1.0 / kd + 1.0 / k_panel) if p.get("keMode", "series") == "series" else kd
    m = Wd * 1000.0 / g                                                # kg
    F_di = p["Co"] * p["V"] * CR * Cs * math.sqrt(k_e * 1000.0 * m) / 1000.0   # kN
    return dict(req=req, CR=CR, Cs=Cs, I=I, k_panel=k_panel, k_e=k_e, m=m, F_di=F_di, a=min(d_f, p["Lp"] / 2))


@dataclass
class FloodDemand:
    """Flood demand on the flood-facing wall, from the card's inputs and Fa selection."""

    params: dict
    sel: Dict[str, bool] = field(default_factory=lambda: {"sta": True, "dyn": True, "di": True})

    # ---- geometry the engine reads from the card -------------------------------------------------
    @property
    def d_f(self) -> float:
        return max(self.params["SWEL"] - self.params["Ge"], 0.0)

    @property
    def h_b(self) -> float:
        p = self.params
        return max(p["Ge"] - p["ELb"], 0.0) if p["bs"] else 0.0

    @property
    def b_eff(self) -> float:
        return self.params["be"]

    @property
    def case_name(self) -> str:
        k = ("1" if self.sel["sta"] else "0") + ("1" if self.sel["dyn"] else "0") + ("1" if self.sel["di"] else "0")
        return {"100": "Hydrostatic only", "010": "Hydrodynamic only", "001": "Debris only", "110": "LC1 · sustained",
                "111": "LC2 · impact", "101": "sta + di", "011": "dyn + di", "000": "no load selected"}[k]

    # ---- the demand ---------------------------------------------------------------------------------
    def demand(self, he: float, wl: Optional[float] = None, ep: bool = True, s: int = -1) -> Dict[str, float]:
        """kN on a panel of width wl for a water head he (m above grade). s = strategy (2 = wet: basement not excluded)."""
        p = self.params
        gw = p["GW"]
        wl = p["be"] if wl is None else wl
        he = max(0.0, he)
        sta = dyn = di = 0.0
        if self.sel["sta"]:
            excl = bool(p["bs"]) and s != 2
            rs = hydrostatic(p["Ge"] + he, p["Ge"], p["ELb"], excl, p["gs"], gw)
            F_dif = 0.5 * (p["gs"] - gw) * max(p["Ge"] - p["ELb"], 0.0) ** 2 if (p["bs"] and ep) else 0.0
            sta = (rs["F_w"] + F_dif) * wl
        if self.sel["dyn"]:
            dyn = hydrodynamic(p, he)["f_dyn"] * wl
        if self.sel["di"]:
            dd = debris(p, he)
            di = dd["F_di"] if dd["req"] else 0.0
        return {"total": sta + dyn + di, "sta": sta, "dyn": dyn, "di": di}

    def design_loads(self) -> Dict[str, float]:
        """Nominal loads at the design flood depth (what the card's KPI strip shows)."""
        p = self.params
        r = hydrostatic(p["SWEL"], p["Ge"], p["ELb"], p["bs"], p["gs"], p["GW"])
        h = hydrodynamic(p, r["d_f"])
        d = debris(p, r["d_f"])
        return {"d_f": r["d_f"], "z": r["z"], "h_b": r["h_b"], "F_sta": r["F_sta"], "z_sta": r["z_sta"],
                "f_dyn": h["f_dyn"], "F_dyn": h["F_dyn"], "Cd": h["Cd"], "F_di": d["F_di"] if d["req"] else 0.0,
                "k_e": d["k_e"], "Fa": self.demand(r["d_f"], p["be"], True, -1)["total"], "case": self.case_name}

    # ---- I/O ----------------------------------------------------------------------------------------
    @classmethod
    def from_state(cls, state: dict) -> "FloodDemand":
        """Build from the JSON of window.FLOOD.state (or from {"params":…, "sel":…})."""
        return cls(dict(state["params"]), dict(state.get("sel") or {"sta": True, "dyn": True, "di": True}))

    @classmethod
    def from_json(cls, path: str) -> "FloodDemand":
        with open(path, encoding="utf-8") as f:
            return cls.from_state(json.load(f))


if __name__ == "__main__":
    import sys

    fd = FloodDemand.from_json(sys.argv[1] if len(sys.argv) > 1 else "pilot_flood_params.json")
    L = fd.design_loads()
    print(f"{L['case']}: d_f = {L['d_f']:.2f} m, z = {L['z']:.2f} m, h_b = {L['h_b']:.2f} m")
    print(f"  F_sta = {L['F_sta']:.1f} kN/m (z_sta {L['z_sta']:.2f} m) | f_dyn = {L['f_dyn']:.2f} kN/m (Cd {L['Cd']:.2f}) "
          f"| F_di = {L['F_di']:.1f} kN (k_e {L['k_e']:.0f} kN/m) | Fa = {L['Fa']:.1f} kN per {fd.b_eff:.1f} m panel")
    for he in (0.5, 1.0, 1.5, L["d_f"], 3.0):
        d = fd.demand(he, fd.b_eff, True, 1)
        w = fd.demand(he, fd.b_eff, True, 2)
        print(f"  he = {he:.2f} m: dry {d['total']:7.1f} kN (sta {d['sta']:.1f} dyn {d['dyn']:.1f} di {d['di']:.1f}) | wet {w['total']:7.1f} kN")
