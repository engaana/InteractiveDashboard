"""Local demo server for the Flood Resilience dashboard.

Serves the dashboard folder over HTTP and exposes /api/run, which executes
the real MOGA engine (moga_flood_preservation.py, NSGA-II) on demand and
returns fresh Pareto results as JSON for the dashboard's 3D chart.

Usage:
    python moga_server.py            # then open http://localhost:8000/interactive_dashboard.html

Requirements: Python 3.9+ and matplotlib (pip install matplotlib).
No other dependencies — the server uses only the standard library.
"""
import json
import time
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import matplotlib

matplotlib.use("Agg")  # headless; the engine module imports matplotlib

import moga_flood_preservation as m

ALL_SEEDS = [11, 22, 33, 44, 55, 66, 77, 88, 99, 111, 121, 131, 141, 151, 161, 171, 181, 191, 201, 211]
PORT = 8000


def run_engine(n_seeds: int, generations: int, profile: dict) -> dict:
    """Run the NSGA-II engine and return dashboard-ready JSON."""
    # Override the building profile with the dashboard's current slider values.
    m.BUILDING_PROFILE["design_flood_depth_m"] = profile["fd"]
    m.BUILDING_PROFILE["masonry_shear_capacity_kN"] = profile["sc"]
    m.BUILDING_PROFILE["wall_length_m"] = profile["wl"]
    m.BUILDING_PROFILE["basement_wall_height_m"] = profile["bh"]

    t0 = time.time()
    seeds = ALL_SEEDS[:n_seeds]
    winners, fronts = [], {}
    for s in seeds:
        w, pop, _hist = m.run_moga(seed=s, population_size=50, generations=generations)
        winners.append(w)
        fronts[s] = m.fast_non_dominated_sort(pop)[0]

    consensus = max(winners, key=lambda c: min(c.objectives))
    points = [
        {
            "seed": sd,
            "s": c.intervention_strategy,
            "st": round(c.objectives[0], 2),
            "pr": round(c.objectives[1], 2),
            "ut": round(c.objectives[2], 2),
            "ph": round(c.protection_height, 3),
            "vif": round(c.visual_impact_factor, 3),
        }
        for sd, front in fronts.items()
        for c in front
    ]
    return {
        "meta": {
            "engine": "moga_flood_preservation.py (NSGA-II) — live run",
            "seeds": seeds,
            "population_size": 50,
            "generations": generations,
            "runtime_seconds": round(time.time() - t0, 1),
            "profile": profile,
        },
        "points": points,
        "winner": {
            "strategy": consensus.intervention_strategy,
            "strategy_name": m.STRATEGY_NAMES[consensus.intervention_strategy],
            "protection_height": round(consensus.protection_height, 3),
            "visual_impact_factor": round(consensus.visual_impact_factor, 3),
            "objectives": [round(x, 2) for x in consensus.objectives],
        },
    }


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        if url.path != "/api/run":
            return super().do_GET()

        q = parse_qs(url.query)

        def num(key, default):
            try:
                return float(q[key][0])
            except (KeyError, ValueError, IndexError):
                return default

        n_seeds = max(1, min(20, int(num("seeds", 5))))
        gens = max(10, min(300, int(num("gens", 60))))
        profile = {
            "fd": max(0.5, min(4.0, num("fd", 2.5))),
            "sc": max(20.0, min(60.0, num("sc", 40.0))),
            "wl": max(1.0, min(3.0, num("wl", 2.0))),
            "bh": max(1.0, min(4.0, num("bh", 2.5))),
        }
        print(f"\n>>> /api/run  seeds={n_seeds} gens={gens} profile={profile}")
        try:
            data = run_engine(n_seeds, gens, profile)
            body = json.dumps(data).encode()
            self.send_response(200)
        except Exception as exc:  # return the error to the dashboard
            body = json.dumps({"error": str(exc)}).encode()
            self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print(f"MOGA demo server running.")
    print(f"Open:  http://localhost:{PORT}/interactive_dashboard.html")
    print("Stop with Ctrl+C.")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
