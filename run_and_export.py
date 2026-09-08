"""Run the full multi-seed MOGA and export dashboard-ready outputs.

Outputs:
  - visualizations/*.png            (all plots from the original script)
  - moga_pareto_data.json           (Pareto points + consensus winner, consumed by interactive_dashboard.html)
  - consultant_report_latest.txt    (text report)

Options (all optional — without them the legacy full run is reproduced):
  --flood pilot_flood_params.json   ASCE 7-22 S2 demand from the Flood Loads card (window.FLOOD.state JSON)
  --case 111                        load components sta/dyn/di as three 0/1 flags (100 hydrostatic, 110 LC1, 111 LC2)
  --sc 70                           masonry shear capacity, kN (dashboard slider)
  --dfe                             pin the protection height to d_f (dry floodproofing to the DFE)
  --no-ep / --no-op                 drop the soil term / the out-of-plane cap
  --seeds 5 --gens 60               size of the run (default 20 seeds × 300 generations)
  --tag pilot_LC2                   suffix for the output files (moga_pareto_data_<tag>.json, …); no figures when set
  --outdir pilot_runs               folder for the tagged outputs (default: current folder)
  --depth-sweep 0.25,0.5,0.75,1,1.25  run at d = frac · d_f (PH pinned to d) and report the winner per depth
"""
import os
import argparse
import json
import time

try:
    import matplotlib

    matplotlib.use("Agg")
except ImportError:  # figures are skipped without matplotlib
    pass

import moga_flood_preservation as m

ap = argparse.ArgumentParser()
ap.add_argument("--flood"); ap.add_argument("--case", default=None); ap.add_argument("--sc", type=float)
ap.add_argument("--dfe", action="store_true"); ap.add_argument("--no-ep", action="store_true"); ap.add_argument("--no-op", action="store_true")
ap.add_argument("--seeds", type=int, default=20); ap.add_argument("--gens", type=int, default=300); ap.add_argument("--tag"); ap.add_argument("--outdir", default=".")
ap.add_argument("--depth-sweep", default=None, help="comma-separated fractions of d_f (requires --flood)")
args = ap.parse_args()

flood_state = None
if args.flood:
    with open(args.flood, encoding="utf-8") as f:
        flood_state = json.load(f)
    if args.case:
        flood_state["sel"] = {"sta": args.case[0] == "1", "dyn": args.case[1] == "1", "di": args.case[2] == "1"}
m.apply_profile({"sc": args.sc, "ep": not args.no_ep, "op": not args.no_op, "dfe": args.dfe}, flood_state)

t0 = time.time()
seeds = [11, 22, 33, 44, 55, 66, 77, 88, 99, 111, 121, 131, 141, 151, 161, 171, 181, 191, 201, 211][: args.seeds]

if args.depth_sweep:
    assert flood_state is not None, "--depth-sweep needs --flood"
    fracs = [float(x) for x in args.depth_sweep.split(",")]
    prof = {"sc": args.sc, "ep": not args.no_ep, "op": not args.no_op}
    res = m.run_depth_sweep(fracs, seeds, args.gens, prof, flood_state)
    res["meta"] = {"engine": "moga_flood_preservation.py (NSGA-II) — depth sweep · ASCE 7-22 S2 demand from the Flood Loads card",
                   "seeds": seeds, "population_size": 50, "generations": args.gens, "runtime_seconds": round(time.time() - t0, 1),
                   "profile": {**prof, "demand": f"ASCE 7-22 S2 · {m.FLOOD_DEMAND.case_name}"}, "sweep_fracs": fracs, "d_f": res["d_f"]}
    os.makedirs(args.outdir, exist_ok=True)
    name = os.path.join(args.outdir, f"moga_depth_sweep{'_' + args.tag if args.tag else ''}.json")
    with open(name, "w") as f:
        json.dump(res, f, indent=1)
    print(f"\n=== Depth sweep — {m.FLOOD_DEMAND.case_name}, d_f = {res['d_f']:.2f} m, {len(seeds)} seeds × {args.gens} generations ===")
    print(f"{'d (m)':>7} {'d/d_f':>6} {'Fa (kN)':>8} {'sta':>6} {'dyn':>5} {'di':>6}  winner                                   St / Pr / Ut")
    for r in res["sweep"]:
        w, fp = r["winner"], r["Fa_parts"]
        print(f"{r['d']:7.2f} {r['frac']:6.2f} {r['Fa']:8.1f} {fp['sta']:6.1f} {fp['dyn']:5.1f} {fp['di']:6.1f}  S{w['strategy']} {w['strategy_name']:<38} "
              f"{w['objectives'][0]:.1f} / {w['objectives'][1]:.1f} / {w['objectives'][2]:.1f}")
    print("Tipping depth (first depth won by wet floodproofing): " + (f"{res['tipping_depth']:.2f} m" if res["tipping_depth"] else "none in range"))
    print(f"Saved: {name}  ({len(res['points'])} Pareto points, {res['meta']['runtime_seconds']}s)")
    raise SystemExit(0)

winner, seed_winners, history_by_seed, pareto_fronts, populations = m.run_multi_seed(seeds, generations=args.gens)
baseline = m.baseline_no_measures()
visuals = [] if args.tag else m.generate_visualizations(winner, seed_winners, history_by_seed, pareto_fronts, populations)
suffix = f"_{args.tag}" if args.tag else ""
os.makedirs(args.outdir, exist_ok=True)
out = lambda name: os.path.join(args.outdir, name)

# --- Export JSON for the dashboard (format expected by drawMoga3D) ---
points = []
for seed, front in pareto_fronts.items():
    for c in front:
        points.append(
            {
                "seed": seed,
                "s": c.intervention_strategy,
                "st": round(c.objectives[0], 2),
                "pr": round(c.objectives[1], 2),
                "ut": round(c.objectives[2], 2),
                "ph": round(c.protection_height, 3),
                "vif": round(c.visual_impact_factor, 3),
            }
        )

data = {
    "meta": {
        "engine": "moga_flood_preservation.py (NSGA-II)" + (" · ASCE 7-22 S2 demand from the Flood Loads card" if m.FLOOD_DEMAND else ""),
        "seeds": seeds,
        "population_size": 50,
        "generations": args.gens,
        "runtime_seconds": None,  # filled below
        "profile": {"fd": m.BUILDING_PROFILE["design_flood_depth_m"], "sc": m.BUILDING_PROFILE["masonry_shear_capacity_kN"],
                    "wl": m.BUILDING_PROFILE["wall_length_m"], "bh": m.BUILDING_PROFILE["basement_wall_height_m"],
                    "ep": m.MODEL_PARAMS["include_earth_pressure"], "op": m.MODEL_PARAMS["include_out_of_plane"],
                    "dfe": m.PH_FIXED is not None,
                    "demand": (f"ASCE 7-22 S2 · {m.FLOOD_DEMAND.case_name}" if m.FLOOD_DEMAND else "legacy hydrostatic + Rankine soil")},
    },
    "points": points,
    "winner": {
        "strategy": winner.intervention_strategy,
        "strategy_name": m.STRATEGY_NAMES[winner.intervention_strategy],
        "protection_height": round(winner.protection_height, 3),
        "visual_impact_factor": round(winner.visual_impact_factor, 3),
        "objectives": [round(x, 2) for x in winner.objectives],
    },
    "baseline_no_measures": [round(x, 2) for x in baseline],
    "seed_winners": [
        {
            "strategy": c.intervention_strategy,
            "protection_height": round(c.protection_height, 3),
            "visual_impact_factor": round(c.visual_impact_factor, 3),
            "objectives": [round(x, 2) for x in c.objectives],
        }
        for c in seed_winners
    ],
}
data["meta"]["runtime_seconds"] = round(time.time() - t0, 1)

with open(out(f"moga_pareto_data{suffix}.json"), "w") as f:
    json.dump(data, f, indent=1)

report = m.consultant_report(winner, baseline)
with open(out(f"consultant_report_latest{suffix}.txt"), "w") as f:
    f.write(report)

print(report)
print(f"Pareto points exported: {len(points)}")
print(f"Total runtime: {data['meta']['runtime_seconds']}s")
print(f"Saved: {out(f'moga_pareto_data{suffix}.json')}")
for p in visuals:
    print("Saved:", p)
