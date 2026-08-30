"""Run the full multi-seed MOGA and export dashboard-ready outputs.

Outputs:
  - visualizations/*.png            (all plots from the original script)
  - moga_pareto_data.json           (Pareto points + consensus winner, consumed by interactive_dashboard.html)
  - consultant_report_latest.txt    (text report)
"""
import json
import time

import matplotlib

matplotlib.use("Agg")

import moga_flood_preservation as m

t0 = time.time()
seeds = [11, 22, 33, 44, 55, 66, 77, 88, 99, 111, 121, 131, 141, 151, 161, 171, 181, 191, 201, 211]

winner, seed_winners, history_by_seed, pareto_fronts, populations = m.run_multi_seed(seeds)
baseline = m.baseline_no_measures()
visuals = m.generate_visualizations(winner, seed_winners, history_by_seed, pareto_fronts, populations)

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
        "engine": "moga_flood_preservation.py (NSGA-II)",
        "seeds": seeds,
        "population_size": 50,
        "generations": 300,
        "runtime_seconds": None,  # filled below
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

with open("moga_pareto_data.json", "w") as f:
    json.dump(data, f, indent=1)

report = m.consultant_report(winner, baseline)
with open("consultant_report_latest.txt", "w") as f:
    f.write(report)

print(report)
print(f"Pareto points exported: {len(points)}")
print(f"Total runtime: {data['meta']['runtime_seconds']}s")
print("Saved: moga_pareto_data.json")
for p in visuals:
    print("Saved:", p)
