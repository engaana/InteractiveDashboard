from __future__ import annotations

from dataclasses import dataclass, field
import math
import os
import random
from statistics import mean
from typing import Dict, List, Tuple

try:  # matplotlib is only needed for the figures (generate_visualizations); the engine and the server run without it
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
except ImportError:  # pragma: no cover
    plt = None
    Rectangle = None


BUILDING_PROFILE = {
    "type": "Two-story unreinforced masonry (URM) with basement",
    "wall_length_m": 2.0,
    "masonry_shear_capacity_kN": 40.0,
    "flood_water_unit_weight_kN_m3": 9.81,
    "first_floor_clear_height_m": 3.2,
    "design_flood_depth_m": 2.5,
    "site_width_m": 30.0,
    "site_height_m": 20.0,
    "building_x_min_m": 8.0,
    "building_x_max_m": 24.0,
    "building_y_min_m": 5.0,
    "building_y_max_m": 15.0,
    "basement_wall_height_m": 2.5,
    "soil_unit_weight_kN_m3": 18.0,
    "soil_k0": 0.5,
    "wall_thickness_m": 0.3,
}

STRATEGY_NAMES = {
    0: "Dry Floodproofing (Sealant/Coating)",
    1: "Dry Floodproofing (Removable Barrier)",
    2: "Wet Floodproofing (Hydrostatic Vents)",
}

STRATEGY_COLORS = {0: "#c44e52", 1: "#4c72b0", 2: "#55a868", 3: "#dd8452"}

# Model-level parameters for transparency and sensitivity checks.
MODEL_PARAMS = {
    "wet_pressure_factor": 0.05,
    "elevation_pressure_factor": 0.4,
    "overtopping_leakage_factor": 0.35,
    "structural_floor_wet": 92.0,
    "structural_floor_elevation": 80.0,
    "risk_aversion_coeff": 0.25,
    "include_earth_pressure": True,
    "include_out_of_plane": True,
    "barrier_deployment_fail_prob": 0.08,
    "barrier_deployment_fail_range": (0.05, 0.15),
}

# ---- Link to the ASCE 7-22 Supplement 2 flood loads (dashboard card) ---------------------------------
# FLOOD_DEMAND: a flood_demand.FloodDemand built from the card's inputs (window.FLOOD.state / pilot_flood_params.json).
#   When set, objective_structural() evaluates the demand on the wall with the load components selected in the
#   card's Fa builder (hydrostatic with basement + submerged soil, hydrodynamic, debris impact) at every hydrograph
#   depth — the same physics as the dashboard surrogate — instead of the legacy ½γh²·L + Rankine earth pressure.
#   When None, the engine behaves exactly as before (legacy model).
# PH_FIXED: pin the protection-height gene (m) — dry floodproofing to the DFE (ASCE 24), i.e. PH = d_f — or None
#   to keep the free 0–3.5 m gene.
FLOOD_DEMAND = None
PH_FIXED: float | None = None


def apply_profile(profile: dict, flood_state: dict | None = None) -> None:
    """Configure the engine from the dashboard: profile = {fd, sc, wl, bh, ep, op, dfe}, flood_state = window.FLOOD.state."""
    global FLOOD_DEMAND, PH_FIXED
    if flood_state is not None:
        from flood_demand import FloodDemand

        FLOOD_DEMAND = FloodDemand.from_state(flood_state)
        BUILDING_PROFILE["design_flood_depth_m"] = FLOOD_DEMAND.d_f
        BUILDING_PROFILE["wall_length_m"] = FLOOD_DEMAND.b_eff
        BUILDING_PROFILE["basement_wall_height_m"] = FLOOD_DEMAND.h_b
    else:
        FLOOD_DEMAND = None
    for key, name in (("fd", "design_flood_depth_m"), ("sc", "masonry_shear_capacity_kN"),
                      ("wl", "wall_length_m"), ("bh", "basement_wall_height_m")):
        # with the card present only "sc" (slider) and "fd" (depth sweep override) may replace the card's values
        if profile.get(key) is not None and (flood_state is None or key in ("sc", "fd")):
            BUILDING_PROFILE[name] = float(profile[key])
    if profile.get("ep") is not None:
        MODEL_PARAMS["include_earth_pressure"] = bool(profile["ep"])
    if profile.get("op") is not None:
        MODEL_PARAMS["include_out_of_plane"] = bool(profile["op"])
    PH_FIXED = round(BUILDING_PROFILE["design_flood_depth_m"], 2) if profile.get("dfe") else None


def candidate_point(seed: int, c: "DesignCandidate", **extra) -> dict:
    """Dashboard-ready record of a candidate (format expected by drawMoga3D)."""
    return {"seed": seed, "s": c.intervention_strategy, "st": round(c.objectives[0], 2), "pr": round(c.objectives[1], 2),
            "ut": round(c.objectives[2], 2), "ph": round(c.protection_height, 3), "vif": round(c.visual_impact_factor, 3), **extra}


def winner_record(c: "DesignCandidate") -> dict:
    return {"strategy": c.intervention_strategy, "strategy_name": STRATEGY_NAMES[c.intervention_strategy],
            "protection_height": round(c.protection_height, 3), "visual_impact_factor": round(c.visual_impact_factor, 3),
            "objectives": [round(x, 2) for x in c.objectives]}


def run_depth_sweep(fracs: List[float], seeds: List[int], generations: int, profile: dict, flood_state: dict) -> dict:
    """Run the MOGA at several flood depths d = frac · d_f (protection height pinned to d in each run).

    Answers "at which depth does the winner flip from dry to wet floodproofing?" — the demand at each depth
    comes from the Flood Loads card physics (hydrostatic, hydrodynamic, debris — the debris term enters above
    0.91 m and reaches its full value at 1.52 m). Returns dashboard-ready JSON: all Pareto points tagged with
    their depth (d, frac), one consensus winner per depth (sweep) and the winner at the design depth.
    """
    from flood_demand import FloodDemand

    d_f = FloodDemand.from_state(flood_state).d_f
    sweep, points = [], []
    for fr in fracs:
        d = round(fr * d_f, 3)
        apply_profile({**profile, "fd": d, "dfe": True}, flood_state)
        winners, fronts = [], {}
        for sd in seeds:
            w, pop, _ = run_moga(seed=sd, population_size=50, generations=generations)
            winners.append(w)
            fronts[sd] = fast_non_dominated_sort(pop)[0]
        cons = max(winners, key=lambda c: min(c.objectives))
        Fa = FLOOD_DEMAND.demand(d, BUILDING_PROFILE["wall_length_m"], MODEL_PARAMS["include_earth_pressure"], -1)
        n0 = len(points)
        for sd, front in fronts.items():
            points.extend(candidate_point(sd, c, d=d, frac=fr) for c in front)
        sweep.append({"frac": fr, "d": d, "Fa": round(Fa["total"], 2), "Fa_parts": {k: round(v, 2) for k, v in Fa.items() if k != "total"},
                      "winner": winner_record(cons), "n_points": len(points) - n0,
                      "seed_winners": [winner_record(w) for w in winners]})
        print(f"Sweep d = {d:.2f} m ({fr:.3g}·d_f): Fa = {Fa['total']:.1f} kN → S{cons.intervention_strategy} {STRATEGY_NAMES[cons.intervention_strategy]} "
              f"objectives={tuple(round(x, 1) for x in cons.objectives)}")
    # design-depth winner: the run closest to frac = 1
    ref = min(sweep, key=lambda r: abs(r["frac"] - 1.0))
    flip = next((r for r in sweep if r["winner"]["strategy"] == 2), None)
    return {"d_f": d_f, "sweep": sweep, "points": points, "winner": ref["winner"],
            "tipping_depth": flip["d"] if flip else None}


def ph_gene(v: float) -> float:
    """Protection-height gene: pinned to the DFE when PH_FIXED is set, else clamped to the 0–3.5 m design space."""
    return PH_FIXED if PH_FIXED is not None else clamp(v, 0.0, 3.5)


@dataclass
class DesignCandidate:
    intervention_strategy: int
    protection_height: float
    visual_impact_factor: float
    objectives: Tuple[float, float, float] = field(default_factory=lambda: (0.0, 0.0, 0.0))
    rank: int = 0
    crowding_distance: float = 0.0

    def clone(self) -> "DesignCandidate":
        return DesignCandidate(
            intervention_strategy=self.intervention_strategy,
            protection_height=self.protection_height,
            visual_impact_factor=self.visual_impact_factor,
            objectives=self.objectives,
            rank=self.rank,
            crowding_distance=self.crowding_distance,
        )


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def hydrostatic_force_kN(h: float, wall_length: float | None = None, gamma: float | None = None) -> float:
    g = gamma if gamma is not None else BUILDING_PROFILE["flood_water_unit_weight_kN_m3"]
    l = wall_length if wall_length is not None else BUILDING_PROFILE["wall_length_m"]
    return 0.5 * g * h * h * l


def earth_pressure_force_kN(h: float, wall_length: float, gamma_soil: float, k0: float) -> float:
    # At-rest earth pressure: resultant = 0.5 * K0 * gamma_soil * h^2 * L
    return 0.5 * k0 * gamma_soil * h * h * wall_length


def bending_capacity_equiv_force_kN(
    flexural_capacity_kNm: float, wall_height: float, wall_length: float
) -> float:
    # Equivalent uniform lateral force producing the same base moment.
    # For a triangular load, base moment = F * h/3 => F = 3M/h.
    if wall_height <= 0:
        return 0.0
    return 3.0 * flexural_capacity_kNm / max(wall_height, 1e-6)


def hydrograph_depths(peak_depth: float, steps: int = 12) -> List[float]:
    # Triangular hydrograph; rise then recession.
    depths = []
    for i in range(steps):
        t = i / (steps - 1)
        if t <= 0.5:
            d = peak_depth * (t / 0.5)
        else:
            d = peak_depth * (1.0 - (t - 0.5) / 0.5)
        depths.append(max(0.0, d))
    return depths


def leakage_depth(
    strategy: int,
    ext_depth: float,
    protection_height: float,
    barrier_reliability: float,
    deployment_fail_prob: float,
) -> float:
    if strategy == 2:
        return ext_depth
    if strategy == 0:
        if ext_depth <= protection_height:
            return 0.08 * ext_depth
        return (ext_depth - protection_height) * 0.92 + 0.1 * protection_height
    # Strategy 1 removable barrier
    # Sample deployment failure from sensitivity range to reflect operational uncertainty.
    eff_reliability = clamp(barrier_reliability - deployment_fail_prob, 0.0, 0.99)
    if ext_depth <= protection_height:
        return 0.03 * ext_depth * (1.0 - eff_reliability)
    overtopped = (ext_depth - protection_height) * (0.55 + 0.35 * (1.0 - eff_reliability))
    return overtopped


def nps_preservation_subscores(candidate: DesignCandidate) -> Dict[str, float]:
    s = candidate.intervention_strategy
    v = candidate.visual_impact_factor

    reversibility = {0: 20.0, 1: 95.0, 2: 85.0}[s]
    # Minimal-visibility preference: near-zero visual impact is favored.
    compatibility = 100.0 - abs(v - 0.1) * 140.0
    compatibility = clamp(compatibility, 0.0, 100.0)
    distinguishability = 100.0 - abs(v - 0.1) * 120.0
    distinguishability = clamp(distinguishability, 0.0, 100.0)

    moisture_risk = {0: 10.0, 1: 75.0, 2: 80.0}[s]
    if s == 0:
        moisture_risk -= 35.0  # sealant trap
    moisture_risk = clamp(moisture_risk, 0.0, 100.0)

    fenestration = 100.0

    return {
        "reversibility": reversibility,
        "compatibility": compatibility,
        "distinguishability": distinguishability,
        "moisture": moisture_risk,
        "fenestration": fenestration,
    }


def objective_preservation(candidate: DesignCandidate) -> float:
    parts = nps_preservation_subscores(candidate)
    # NPS-oriented weighting with explicit criteria.
    score = (
        0.30 * parts["reversibility"]
        + 0.18 * parts["compatibility"]
        + 0.12 * parts["distinguishability"]
        + 0.28 * parts["moisture"]
        + 0.12 * parts["fenestration"]
    )
    if candidate.intervention_strategy == 0:
        score -= 15.0
    if candidate.intervention_strategy == 1:
        score += 6.0
    return clamp(score, 0.0, 100.0)


def objective_structural(candidate: DesignCandidate, scenario: Dict[str, float]) -> float:
    strategy = candidate.intervention_strategy
    cap = scenario["shear_capacity_kN"]
    wall_l = scenario["wall_length_m"]
    gamma = scenario["gamma_kN_m3"]
    barrier_reliability = scenario["barrier_reliability"]
    deploy_fail = scenario["deployment_fail_prob"]
    gamma_soil = scenario["soil_unit_weight_kN_m3"]
    k0 = scenario["soil_k0"]
    flex_cap = scenario["flexural_capacity_kNm"]
    basement_h = scenario["basement_wall_height_m"]

    peak_force = 0.0
    for d in hydrograph_depths(scenario["peak_depth_m"], steps=12):
        if strategy in (0, 1):
            h_eff = min(d, candidate.protection_height)
            if d > candidate.protection_height:
                h_eff += leakage_depth(
                    strategy,
                    d,
                    candidate.protection_height,
                    barrier_reliability,
                    deploy_fail,
                ) * MODEL_PARAMS[
                    "overtopping_leakage_factor"
                ]
        elif strategy == 2:
            h_eff = MODEL_PARAMS["wet_pressure_factor"] * d
        if FLOOD_DEMAND is not None:
            # ASCE 7-22 S2 demand selected in the Flood Loads card (hydrostatic / hydrodynamic / debris) on the panel
            f = FLOOD_DEMAND.demand(h_eff, wall_l, MODEL_PARAMS["include_earth_pressure"], strategy)["total"]
        else:
            f = hydrostatic_force_kN(h_eff, wall_length=wall_l, gamma=gamma)
            if MODEL_PARAMS["include_earth_pressure"]:
                f += earth_pressure_force_kN(min(basement_h, h_eff), wall_l, gamma_soil, k0)
        peak_force = max(peak_force, f)

    # Optional out-of-plane bending check (converted to equivalent force capacity).
    if MODEL_PARAMS["include_out_of_plane"]:
        flex_equiv = bending_capacity_equiv_force_kN(flex_cap, max(basement_h, 0.1), wall_l)
        cap = min(cap, flex_equiv)

    if strategy in (0, 1) and peak_force > cap:
        return 0.0
    ratio = clamp(peak_force / cap, 0.0, 2.0)
    base = 100.0 * (1.0 - ratio)
    if strategy == 2:
        base = max(base, MODEL_PARAMS["structural_floor_wet"])
    return clamp(base, 0.0, 100.0)


def objective_utility(candidate: DesignCandidate, scenario: Dict[str, float]) -> float:
    strategy = candidate.intervention_strategy
    depths = hydrograph_depths(scenario["peak_depth_m"], steps=12)
    barrier_reliability = scenario["barrier_reliability"]
    deploy_fail = scenario["deployment_fail_prob"]

    interior_depths = [
        leakage_depth(strategy, d, candidate.protection_height, barrier_reliability, deploy_fail) for d in depths
    ]
    wet_hours = sum(1 for d in interior_depths if d > 0.1)
    peak_inside = max(interior_depths)

    if strategy == 2:
        immediate = 0.0
    else:
        immediate = clamp(100.0 - 35.0 * peak_inside - 4.0 * wet_hours, 0.0, 100.0)

    recovery_penalty_days = 8.0 * peak_inside + 0.6 * wet_hours
    if strategy == 0:
        recovery_penalty_days += 4.0
    if strategy == 1:
        recovery_penalty_days -= 1.5

    lifecycle_cost_norm = {
        0: 0.50,
        1: 0.35,
        2: 0.45,
    }[strategy]
    cost_score = 100.0 * (1.0 - lifecycle_cost_norm)

    recovery_score = clamp(100.0 - 7.0 * recovery_penalty_days, 0.0, 100.0)
    return clamp(0.5 * immediate + 0.3 * recovery_score + 0.2 * cost_score, 0.0, 100.0)


def evaluate(candidate: DesignCandidate, scenario: Dict[str, float]) -> Tuple[float, float, float]:
    candidate.objectives = (
        objective_structural(candidate, scenario),
        objective_preservation(candidate),
        objective_utility(candidate, scenario),
    )
    return candidate.objectives


def sample_scenario(rng: random.Random) -> Dict[str, float]:
    fail_lo, fail_hi = MODEL_PARAMS["barrier_deployment_fail_range"]
    fd, sc, wl = BUILDING_PROFILE["design_flood_depth_m"], BUILDING_PROFILE["masonry_shear_capacity_kN"], BUILDING_PROFILE["wall_length_m"]
    return {
        # scatter and bounds are relative to the profile (σ 14 % / 15 % / 12.5 %, bounds 0.56–1.4 / 0.6–1.3 / 0.75–1.4 ×),
        # which reproduces the original absolute values at the original profile (2.5 m, 40 kN, 2.0 m)
        "peak_depth_m": clamp(rng.gauss(fd, 0.14 * fd), 0.56 * fd, 1.4 * fd),
        "shear_capacity_kN": clamp(rng.gauss(sc, 0.15 * sc), 0.6 * sc, 1.3 * sc),
        "gamma_kN_m3": clamp(rng.gauss(BUILDING_PROFILE["flood_water_unit_weight_kN_m3"], 0.5), 8.5, 10.5),
        "wall_length_m": clamp(rng.gauss(wl, 0.125 * wl), 0.75 * wl, 1.4 * wl),
        "barrier_reliability": clamp(rng.gauss(0.87, 0.08), 0.5, 0.99),
        "deployment_fail_prob": rng.uniform(fail_lo, fail_hi),
        "soil_unit_weight_kN_m3": clamp(rng.gauss(BUILDING_PROFILE["soil_unit_weight_kN_m3"], 1.2), 16.0, 21.0),
        "soil_k0": clamp(rng.gauss(BUILDING_PROFILE["soil_k0"], 0.08), 0.35, 0.65),
        "basement_wall_height_m": BUILDING_PROFILE["basement_wall_height_m"],
        # Flexural capacity is a proxy; user should calibrate for specific URM detailing.
        "flexural_capacity_kNm": clamp(rng.gauss(55.0, 10.0), 30.0, 85.0),
    }


def evaluate_robust(candidate: DesignCandidate, rng: random.Random, mc_samples: int = 20) -> Tuple[float, float, float]:
    scores: List[Tuple[float, float, float]] = []
    for _ in range(mc_samples):
        s = sample_scenario(rng)
        scores.append(
            (
                objective_structural(candidate, s),
                objective_preservation(candidate),
                objective_utility(candidate, s),
            )
        )
    # Risk-averse aggregation: mean - 0.5*std proxy via percentile spread.
    out = []
    for j in range(3):
        vals = sorted(x[j] for x in scores)
        p20 = vals[max(0, int(0.2 * (len(vals) - 1)))]
        p80 = vals[int(0.8 * (len(vals) - 1))]
        robust = mean(vals) - MODEL_PARAMS["risk_aversion_coeff"] * (p80 - p20)
        out.append(clamp(robust, 0.0, 100.0))
    candidate.objectives = (out[0], out[1], out[2])
    return candidate.objectives


def dominates(a: DesignCandidate, b: DesignCandidate) -> bool:
    no_worse = all(x >= y for x, y in zip(a.objectives, b.objectives))
    better = any(x > y for x, y in zip(a.objectives, b.objectives))
    return no_worse and better


def fast_non_dominated_sort(population: List[DesignCandidate]) -> List[List[DesignCandidate]]:
    fronts: List[List[DesignCandidate]] = [[]]
    n = len(population)
    dom_sets = [[] for _ in range(n)]
    dom_counts = [0] * n
    id_to_idx = {id(c): i for i, c in enumerate(population)}

    for i, p in enumerate(population):
        for j, q in enumerate(population):
            if i == j:
                continue
            if dominates(p, q):
                dom_sets[i].append(j)
            elif dominates(q, p):
                dom_counts[i] += 1
        if dom_counts[i] == 0:
            p.rank = 0
            fronts[0].append(p)

    k = 0
    while k < len(fronts) and fronts[k]:
        nxt = []
        for p in fronts[k]:
            pi = id_to_idx[id(p)]
            for qj in dom_sets[pi]:
                dom_counts[qj] -= 1
                if dom_counts[qj] == 0:
                    population[qj].rank = k + 1
                    nxt.append(population[qj])
        k += 1
        fronts.append(nxt)

    if not fronts[-1]:
        fronts.pop()
    return fronts


def assign_crowding_distance(front: List[DesignCandidate]) -> None:
    if not front:
        return
    for c in front:
        c.crowding_distance = 0.0
    for m in range(3):
        front.sort(key=lambda x: x.objectives[m])
        front[0].crowding_distance = float("inf")
        front[-1].crowding_distance = float("inf")
        mn = front[0].objectives[m]
        mx = front[-1].objectives[m]
        if math.isclose(mn, mx):
            continue
        for i in range(1, len(front) - 1):
            front[i].crowding_distance += (front[i + 1].objectives[m] - front[i - 1].objectives[m]) / (mx - mn)


def tournament_select(population: List[DesignCandidate], rng: random.Random) -> DesignCandidate:
    a = rng.choice(population)
    b = rng.choice(population)
    if a.rank != b.rank:
        return a if a.rank < b.rank else b
    if a.crowding_distance != b.crowding_distance:
        return a if a.crowding_distance > b.crowding_distance else b
    return a if rng.random() < 0.5 else b


def crossover(p1: DesignCandidate, p2: DesignCandidate, rng: random.Random) -> Tuple[DesignCandidate, DesignCandidate]:
    c1, c2 = p1.clone(), p2.clone()
    if rng.random() < 0.9:
        if rng.random() < 0.5:
            c1.intervention_strategy, c2.intervention_strategy = c2.intervention_strategy, c1.intervention_strategy
        a = rng.random()
        b = rng.random()
        c1.protection_height = a * p1.protection_height + (1 - a) * p2.protection_height
        c2.protection_height = a * p2.protection_height + (1 - a) * p1.protection_height
        c1.visual_impact_factor = b * p1.visual_impact_factor + (1 - b) * p2.visual_impact_factor
        c2.visual_impact_factor = b * p2.visual_impact_factor + (1 - b) * p1.visual_impact_factor
    c1.protection_height = ph_gene(c1.protection_height)
    c2.protection_height = ph_gene(c2.protection_height)
    c1.visual_impact_factor = clamp(c1.visual_impact_factor, 0.0, 1.0)
    c2.visual_impact_factor = clamp(c2.visual_impact_factor, 0.0, 1.0)
    return c1, c2


def mutate(c: DesignCandidate, rng: random.Random, rate: float = 0.18) -> None:
    if rng.random() < rate:
        c.intervention_strategy = rng.randint(0, 2)
    if rng.random() < rate:
        c.protection_height = ph_gene(c.protection_height + rng.uniform(-0.5, 0.5))
    if rng.random() < rate:
        c.visual_impact_factor = clamp(c.visual_impact_factor + rng.uniform(-0.22, 0.22), 0.0, 1.0)


def sanity_check_population(population: List[DesignCandidate], rng: random.Random) -> bool:
    sealant_count = sum(1 for c in population if c.intervention_strategy == 0)
    if sealant_count / len(population) >= 0.55:
        print("Warning: Population converging on damaging intervention. Injecting mutation to force exploration of Wet Floodproofing.")
        sealants = [c for c in population if c.intervention_strategy == 0]
        rng.shuffle(sealants)
        for c in sealants[: max(1, len(population) // 5)]:
            c.intervention_strategy = 2
            c.visual_impact_factor = clamp(0.35 + rng.uniform(-0.1, 0.1), 0.0, 1.0)
        return True
    return False


def initialize_population(n: int, rng: random.Random) -> List[DesignCandidate]:
    return [
        DesignCandidate(rng.randint(0, 2), ph_gene(rng.uniform(0.0, 3.5)), rng.uniform(0.0, 1.0))
        for _ in range(n)
    ]


def evaluate_population(pop: List[DesignCandidate], rng: random.Random, mc_samples: int = 12) -> None:
    for c in pop:
        evaluate_robust(c, rng, mc_samples=mc_samples)


def next_generation(pop: List[DesignCandidate], pop_size: int, rng: random.Random) -> List[DesignCandidate]:
    fronts = fast_non_dominated_sort(pop)
    for f in fronts:
        assign_crowding_distance(f)

    children: List[DesignCandidate] = []
    while len(children) < pop_size:
        p1 = tournament_select(pop, rng)
        p2 = tournament_select(pop, rng)
        c1, c2 = crossover(p1, p2, rng)
        mutate(c1, rng)
        mutate(c2, rng)
        children.append(c1)
        if len(children) < pop_size:
            children.append(c2)

    evaluate_population(children, rng, mc_samples=10)

    combined = pop + children
    fronts = fast_non_dominated_sort(combined)
    out: List[DesignCandidate] = []
    for f in fronts:
        assign_crowding_distance(f)
        if len(out) + len(f) <= pop_size:
            out.extend(f)
        else:
            out.extend(sorted(f, key=lambda x: x.crowding_distance, reverse=True)[: pop_size - len(out)])
            break
    return out


def balanced_pick(front: List[DesignCandidate]) -> DesignCandidate:
    return max(front, key=lambda c: min(c.objectives))


def run_moga(seed: int, population_size: int = 50, generations: int = 50) -> Tuple[DesignCandidate, List[DesignCandidate], List[Dict[str, float]]]:
    rng = random.Random(seed)
    pop = initialize_population(population_size, rng)
    evaluate_population(pop, rng, mc_samples=14)
    history: List[Dict[str, float]] = []
    sanity_triggers = 0

    for g in range(1, generations + 1):
        if sanity_check_population(pop, rng):
            sanity_triggers += 1
        pop = next_generation(pop, population_size, rng)
        front = fast_non_dominated_sort(pop)[0]
        rep = balanced_pick(front)
        history.append({"generation": g, "structural": rep.objectives[0], "preservation": rep.objectives[1], "utility": rep.objectives[2]})
        if g in (1, 10, 20, 30, 40, 50):
            print(f"Seed {seed} Gen {g:02d}: strategy={rep.intervention_strategy} objectives={tuple(round(x, 2) for x in rep.objectives)}")

    front = fast_non_dominated_sort(pop)[0]
    print(f"Seed {seed}: sanity_check_triggered={sanity_triggers} times")
    return balanced_pick(front), pop, history


def pareto_stats(front: List[DesignCandidate]) -> Dict[str, float]:
    if not front:
        return {}
    s_vals = [c.objectives[0] for c in front]
    p_vals = [c.objectives[1] for c in front]
    u_vals = [c.objectives[2] for c in front]
    return {
        "count": len(front),
        "struct_min": min(s_vals),
        "struct_max": max(s_vals),
        "pres_min": min(p_vals),
        "pres_max": max(p_vals),
        "util_min": min(u_vals),
        "util_max": max(u_vals),
    }


def simulate_spatial_flood_depth_grid(strategy: int, protection_height: float, peak_depth: float, nx: int = 120, ny: int = 80) -> Tuple[List[List[float]], Dict[str, float]]:
    site_w, site_h = BUILDING_PROFILE["site_width_m"], BUILDING_PROFILE["site_height_m"]
    bx0, bx1 = BUILDING_PROFILE["building_x_min_m"], BUILDING_PROFILE["building_x_max_m"]
    by0, by1 = BUILDING_PROFILE["building_y_min_m"], BUILDING_PROFILE["building_y_max_m"]
    dx, dy = site_w / (nx - 1), site_h / (ny - 1)

    grid = [[0.0 for _ in range(nx)] for _ in range(ny)]
    interior = []
    for j in range(ny):
        y = j * dy
        for i in range(nx):
            x = i * dx
            ext = clamp(peak_depth * (1.0 - 0.14 * (x / site_w) + 0.04 * (y / site_h)), 0.0, peak_depth)
            inside = bx0 <= x <= bx1 and by0 <= y <= by1
            if not inside:
                depth = ext
            else:
                depth = leakage_depth(strategy, ext, protection_height, barrier_reliability=0.88, deployment_fail_prob=0.1)
                depth *= (0.95 + 0.08 * (x - bx0) / (bx1 - bx0))
                interior.append(depth)
            grid[j][i] = clamp(depth, 0.0, peak_depth)

    return grid, {
        "site_w": site_w,
        "site_h": site_h,
        "building_x_min": bx0,
        "building_x_max": bx1,
        "building_y_min": by0,
        "building_y_max": by1,
        "mean_interior_depth": mean(interior) if interior else 0.0,
        "max_interior_depth": max(interior) if interior else 0.0,
        "peak_depth": peak_depth,
    }


def plot_spatial_depth_grid(depth_grid: List[List[float]], meta: Dict[str, float], title: str, out_path: str) -> None:
    fig, ax = plt.subplots(figsize=(8.3, 5.2))
    im = ax.imshow(depth_grid, origin="lower", extent=[0, meta["site_w"], 0, meta["site_h"]], cmap="Blues", vmin=0.0, vmax=meta["peak_depth"], aspect="auto")
    bx0, bx1 = meta["building_x_min"], meta["building_x_max"]
    by0, by1 = meta["building_y_min"], meta["building_y_max"]
    ax.add_patch(Rectangle((bx0, by0), bx1 - bx0, by1 - by0, fill=False, edgecolor="#333", linewidth=1.8))
    ax.text(bx0 + 0.2, by1 + 0.3, f"Mean in={meta['mean_interior_depth']:.2f} m | Max in={meta['max_interior_depth']:.2f} m", fontsize=8)
    ax.set_title(title)
    ax.set_xlabel("Site X (m)")
    ax.set_ylabel("Site Y (m)")
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Flood depth above occupied-floor datum (m)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=170)
    plt.close(fig)


def plot_generation_trends(history_by_seed: Dict[int, List[Dict[str, float]]], out_path: str) -> None:
    fig, ax = plt.subplots(figsize=(8.5, 5))
    for seed, hist in history_by_seed.items():
        g = [h["generation"] for h in hist]
        u = [h["utility"] for h in hist]
        ax.plot(g, u, linewidth=1.2, alpha=0.6, label=f"Seed {seed}")
    ax.set_title("Multi-Seed Utility Trajectories")
    ax.set_xlabel("Generation")
    ax.set_ylabel("Utility score (representative front point)")
    ax.grid(alpha=0.2)
    ax.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    fig.savefig(out_path, dpi=170)
    plt.close(fig)


def plot_seed_envelope(seed_winners: List[DesignCandidate], out_path: str) -> None:
    fig, ax = plt.subplots(figsize=(7.6, 5.2))
    ax.scatter(
        [c.objectives[0] for c in seed_winners],
        [c.objectives[2] for c in seed_winners],
        s=[40 + c.objectives[2] for c in seed_winners],
        c=[STRATEGY_COLORS[c.intervention_strategy] for c in seed_winners],
        alpha=0.75,
    )
    ax.set_title("Decision Envelope Across Seeds\n(size = utility)")
    ax.set_xlabel("Structural")
    ax.set_ylabel("Utility")
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(out_path, dpi=170)
    plt.close(fig)


def plot_pareto_fronts_by_seed(
    pareto_fronts: Dict[int, List[DesignCandidate]],
    winner: DesignCandidate,
    populations: Dict[int, List[DesignCandidate]],
    out_path: str,
) -> None:
    fig, ax = plt.subplots(figsize=(8.2, 5.4))
    # Size markers by utility with a clearer visual spread.
    all_utils = [c.objectives[2] for front in pareto_fronts.values() for c in front]
    u_min = min(all_utils) if all_utils else 0.0
    u_max = max(all_utils) if all_utils else 1.0
    spread = max(u_max - u_min, 1e-6)

    for idx, (seed, front) in enumerate(sorted(pareto_fronts.items(), key=lambda x: x[0])):
        # Dominated points as outlines only.
        pop = populations.get(seed, [])
        front_ids = {id(c) for c in front}
        dominated = [c for c in pop if id(c) not in front_ids]
        if dominated:
            dom_sizes = [40.0 + 160.0 * ((c.objectives[2] - u_min) / spread) for c in dominated]
            # Draw dominated per strategy so color mapping is explicit.
            for s in range(4):
                subset = [c for c in dominated if c.intervention_strategy == s]
                if not subset:
                    continue
                sub_sizes = [
                    40.0 + 160.0 * ((c.objectives[2] - u_min) / spread) for c in subset
                ]
                ax.scatter(
                    [c.objectives[0] for c in subset],
                    [c.objectives[1] for c in subset],
                    s=sub_sizes,
                    facecolors="none",
                    edgecolors=STRATEGY_COLORS[s],
                    linewidths=0.9,
                    alpha=0.75,
                    marker="o",
                    label="Dominated candidates" if (idx == 0 and s == 0) else None,
                )
        # Draw Pareto points per strategy to ensure color mapping is explicit.
        for s in range(4):
            subset = [c for c in front if c.intervention_strategy == s]
            if not subset:
                continue
            sub_sizes = [30.0 + 140.0 * ((c.objectives[2] - u_min) / spread) for c in subset]
            ax.scatter(
                [c.objectives[0] for c in subset],
                [c.objectives[1] for c in subset],
                s=sub_sizes,
                c=STRATEGY_COLORS[s],
                alpha=0.55,
                marker="o",
                label=None,
                edgecolors="white",
                linewidths=0.3,
            )
    ax.scatter(
        [winner.objectives[0]],
        [winner.objectives[1]],
        s=260,
        marker="*",
        c="#000000",
        edgecolors="white",
        linewidths=0.8,
        label="Selected winner",
    )
    # Build strategy legend only (seed is not encoded in the plot).
    strategy_handles = []
    for s in range(4):
        strategy_handles.append(
            plt.Line2D(
                [0],
                [0],
                marker="o",
                color="none",
                markerfacecolor=STRATEGY_COLORS[s],
                markeredgecolor="white",
                markersize=8,
                linestyle="",
                label=f"Strategy {s}",
            )
        )

    leg_strategy = ax.legend(
        handles=strategy_handles, fontsize=7, ncol=2, title="Strategy", loc="upper right", frameon=True
    )
    ax.add_artist(leg_strategy)
    ax.set_title("Pareto Fronts (color = strategy, size = utility)")
    ax.set_xlabel("Structural")
    ax.set_ylabel("Preservation")
    ax.grid(alpha=0.2)
    # No additional legend; strategy legend is already added.
    fig.tight_layout()
    fig.savefig(out_path, dpi=170)
    plt.close(fig)


def plot_strategy_depth_summary(summary: List[Tuple[str, float, float]], out_path: str) -> None:
    labels = [x[0] for x in summary]
    means = [x[1] for x in summary]
    maxs = [x[2] for x in summary]
    x = list(range(len(summary)))
    w = 0.38
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar([i - w / 2 for i in x], means, width=w, color="#4c72b0", label="Mean interior depth")
    ax.bar([i + w / 2 for i in x], maxs, width=w, color="#c44e52", label="Max interior depth")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=18, ha="right")
    ax.set_ylabel("Depth (m)")
    ax.set_title("2D Grid Flood Outcomes by Strategy")
    ax.grid(axis="y", alpha=0.2)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=170)
    plt.close(fig)


def plot_pairwise_fronts(pareto_fronts: Dict[int, List[DesignCandidate]], out_dir: str) -> List[str]:
    # Combine all Pareto points across seeds for visualization.
    points = []
    for front in pareto_fronts.values():
        points.extend(front)

    if not points:
        return []

    pairs = [
        ("Structural", "Preservation", 0, 1),
        ("Structural", "Utility", 0, 2),
        ("Preservation", "Utility", 1, 2),
    ]

    out_paths = []
    for x_label, y_label, xi, yi in pairs:
        fig, ax = plt.subplots(figsize=(7.6, 5.2))
        for s in range(4):
            subset = [c for c in points if c.intervention_strategy == s]
            if not subset:
                continue
            ax.scatter(
                [c.objectives[xi] for c in subset],
                [c.objectives[yi] for c in subset],
                s=28,
                c=STRATEGY_COLORS[s],
                alpha=0.65,
                label=f"Strategy {s}",
                edgecolors="white",
                linewidths=0.3,
            )
        ax.set_xlabel(x_label)
        ax.set_ylabel(y_label)
        ax.set_title(f"Pairwise Pareto Projection: {x_label} vs {y_label}")
        ax.grid(alpha=0.2)
        ax.legend(fontsize=7, ncol=2)
        fig.tight_layout()
        out_path = os.path.join(out_dir, f"pareto_pair_{x_label.lower()}_{y_label.lower()}.png")
        fig.savefig(out_path, dpi=170)
        plt.close(fig)
        out_paths.append(out_path)
    return out_paths

def baseline_no_measures() -> Tuple[float, float, float]:
    # Scenario-based baseline no-measures score.
    rng = random.Random(2026)
    tmp = DesignCandidate(intervention_strategy=2, protection_height=0.0, visual_impact_factor=0.4)
    vals = []
    for _ in range(40):
        s = sample_scenario(rng)
        d = s["peak_depth_m"]
        if FLOOD_DEMAND is not None:
            force = FLOOD_DEMAND.demand(d, s["wall_length_m"], MODEL_PARAMS["include_earth_pressure"], -1)["total"]
        else:
            force = hydrostatic_force_kN(d, wall_length=s["wall_length_m"], gamma=s["gamma_kN_m3"])
        structural = 0.0 if force > s["shear_capacity_kN"] else clamp(100.0 * (1.0 - force / s["shear_capacity_kN"]), 0.0, 100.0)
        preservation = clamp(18.0 - 8.0 * max(0.0, d - 1.5), 0.0, 100.0)
        utility = clamp(10.0 - 3.0 * d, 0.0, 100.0)
        vals.append((structural, preservation, utility))
    return (mean([v[0] for v in vals]), mean([v[1] for v in vals]), mean([v[2] for v in vals]))


def consultant_report(winner: DesignCandidate, baseline: Tuple[float, float, float]) -> str:
    ws, wp, wu = winner.objectives
    bs, bp, bu = baseline
    return (
        "\n=== Consultant Report ===\n"
        f"Building: {BUILDING_PROFILE['type']} in FEMA AE Zone\n"
        + (f"Flood demand: ASCE 7-22 S2 — {FLOOD_DEMAND.case_name} (d_f {FLOOD_DEMAND.d_f:.2f} m, b_eff {FLOOD_DEMAND.b_eff:.2f} m, "
           f"h_b {FLOOD_DEMAND.h_b:.2f} m)\n" if FLOOD_DEMAND is not None else "Flood demand: legacy hydrostatic ½γh² + Rankine soil\n")
        + (f"Protection height pinned to the DFE: PH = d_f = {PH_FIXED:.2f} m\n" if PH_FIXED is not None else "")
        + 
        f"Selected Strategy: {STRATEGY_NAMES[winner.intervention_strategy]}\n"
        f"Selected Genes: protection_height={winner.protection_height:.2f} m, visual_impact_factor={winner.visual_impact_factor:.2f}\n"
        f"Selected Objectives: Structural={ws:.1f}, Preservation={wp:.1f}, Utility={wu:.1f}\n"
        f"No-Measure Baseline: Structural={bs:.1f}, Preservation={bp:.1f}, Utility={bu:.1f}\n"
        "Trade-off Rationale: We selected Strategy "
        f"{winner.intervention_strategy} because although Strategy Dry Floodproofing (Sealant/Coating) can block more water in idealized cases, "
        "it violates NPS Standard 9 risk boundaries by increasing irreversible masonry moisture/salt damage.\n"
    )


def generate_visualizations(
    winner: DesignCandidate,
    seed_winners: List[DesignCandidate],
    history_by_seed: Dict[int, List[Dict[str, float]]],
    pareto_fronts: Dict[int, List[DesignCandidate]],
    populations: Dict[int, List[DesignCandidate]],
) -> List[str]:
    if plt is None:
        print("matplotlib not installed — skipping the figures (pip install matplotlib)")
        return []
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "visualizations")
    os.makedirs(out_dir, exist_ok=True)
    paths = []

    peak = BUILDING_PROFILE["design_flood_depth_m"]
    summary = []
    for s in range(3):
        grid, meta = simulate_spatial_flood_depth_grid(s, winner.protection_height, peak_depth=peak)
        p = os.path.join(out_dir, f"spatial_strategy_{s}_depth_grid.png")
        plot_spatial_depth_grid(grid, meta, f"2D Flood Depth Grid: Strategy {s} ({STRATEGY_NAMES[s]})", p)
        paths.append(p)
        summary.append((f"Strategy {s}", meta["mean_interior_depth"], meta["max_interior_depth"]))

    bg, bm = simulate_spatial_flood_depth_grid(2, 0.0, peak_depth=peak)  # treat as flooded interior baseline proxy
    p0 = os.path.join(out_dir, "spatial_baseline_no_measures.png")
    plot_spatial_depth_grid(bg, bm, "2D Flood Depth Grid: Baseline (No Measures)", p0)
    paths.append(p0)
    summary.insert(0, ("No measures", bm["mean_interior_depth"], bm["max_interior_depth"]))

    p1 = os.path.join(out_dir, "spatial_depth_summary.png")
    plot_strategy_depth_summary(summary, p1)
    paths.append(p1)

    p2 = os.path.join(out_dir, "seed_envelope.png")
    plot_seed_envelope(seed_winners, p2)
    paths.append(p2)

    p2b = os.path.join(out_dir, "pareto_fronts_multiseed.png")
    plot_pareto_fronts_by_seed(pareto_fronts, winner, populations, p2b)
    paths.append(p2b)

    pairwise_paths = plot_pairwise_fronts(pareto_fronts, out_dir)
    paths.extend(pairwise_paths)

    p3 = os.path.join(out_dir, "generation_trends_multiseed.png")
    plot_generation_trends(history_by_seed, p3)
    paths.append(p3)

    return paths


def run_multi_seed(
    seed_list: List[int],
    generations: int = 300,
) -> Tuple[
    DesignCandidate,
    List[DesignCandidate],
    Dict[int, List[Dict[str, float]]],
    Dict[int, List[DesignCandidate]],
    Dict[int, List[DesignCandidate]],
]:
    winners = []
    history = {}
    pareto_fronts = {}
    populations = {}
    for s in seed_list:
        w, pop, h = run_moga(seed=s, population_size=50, generations=generations)
        winners.append(w)
        history[s] = h
        pareto_fronts[s] = fast_non_dominated_sort(pop)[0]
        populations[s] = pop

    # Robust consensus winner: maximize minimum objective among seed winners.
    consensus = max(winners, key=lambda c: min(c.objectives))
    # Print Pareto stats for transparency.
    for seed, front in pareto_fronts.items():
        stats = pareto_stats(front)
        if stats:
            print(
                f"Seed {seed} Pareto stats: "
                f"count={stats['count']} "
                f"struct=({stats['struct_min']:.1f},{stats['struct_max']:.1f}) "
                f"pres=({stats['pres_min']:.1f},{stats['pres_max']:.1f}) "
                f"util=({stats['util_min']:.1f},{stats['util_max']:.1f})"
            )
    return consensus, winners, history, pareto_fronts, populations


def main() -> None:
    seeds = [11, 22, 33, 44, 55, 66, 77, 88, 99, 111, 121, 131, 141, 151, 161, 171, 181, 191, 201, 211]
    winner, seed_winners, history_by_seed, pareto_fronts, populations = run_multi_seed(seeds)
    baseline = baseline_no_measures()
    visuals = generate_visualizations(winner, seed_winners, history_by_seed, pareto_fronts, populations)

    print("\n=== Optimization Winner (Multi-Seed Robust) ===")
    print(f"Intervention Strategy: {winner.intervention_strategy} ({STRATEGY_NAMES[winner.intervention_strategy]})")
    print(f"Protection Height: {winner.protection_height:.2f} m")
    print(f"Visual Impact Factor: {winner.visual_impact_factor:.2f}")
    print(
        "Objective Scores (A Structural, B Preservation, C Utility): "
        f"({winner.objectives[0]:.1f}, {winner.objectives[1]:.1f}, {winner.objectives[2]:.1f})"
    )
    print(consultant_report(winner, baseline))
    print(f"Risk-aversion coeff (S_robust): {MODEL_PARAMS['risk_aversion_coeff']}")
    print(f"Wet pressure factor: {MODEL_PARAMS['wet_pressure_factor']}")
    print(f"Elevation pressure factor: {MODEL_PARAMS['elevation_pressure_factor']}")
    print(f"Include earth pressure: {MODEL_PARAMS['include_earth_pressure']}")
    print(f"Include out-of-plane bending: {MODEL_PARAMS['include_out_of_plane']}")
    print("=== Saved Visualizations ===")
    for p in visuals:
        print(p)


if __name__ == "__main__":
    main()
