"""Local demo server for the Flood Resilience dashboard.

Serves the dashboard folder over HTTP and exposes /api/run, which executes
the real MOGA engine (moga_flood_preservation.py, NSGA-II) on demand and
returns fresh Pareto results as JSON for the dashboard's 3D chart.

POST /api/run (used by the dashboard since the Flood Loads card was linked) takes a JSON body
    {"seeds": 5, "gens": 60, "profile": {"sc": 70, "ep": true, "op": true, "dfe": true},
     "flood": <window.FLOOD.state>, "sweep": [0.25, 0.5, 0.75, 1, 1.25]}   # sweep optional: d = frac · d_f
and runs the engine with the ASCE 7-22 S2 demand selected in the card (flood_demand.py).
GET /api/run?seeds=&gens=&fd=&sc=&wl=&bh= still runs the legacy model (no card).

Usage:
    python moga_server.py            # then open http://localhost:8000/interactive_dashboard.html

Requirements: Python 3.9+ — standard library only (matplotlib is optional, for the engine's figures).
"""
import json
import threading
import time
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

try:
    import matplotlib

    matplotlib.use("Agg")  # headless; only needed for the engine's figures
except ImportError:
    pass

import moga_flood_preservation as m

RUN_LOCK = threading.Lock()   # the engine keeps its profile in module globals → one run at a time
ALL_SEEDS = [11, 22, 33, 44, 55, 66, 77, 88, 99, 111, 121, 131, 141, 151, 161, 171, 181, 191, 201, 211]
PORT = 8000


def run_engine(n_seeds: int, generations: int, profile: dict, flood: dict | None = None, sweep: list | None = None) -> dict:
    """Run the NSGA-II engine and return dashboard-ready JSON."""
    # Building profile from the dashboard (and the ASCE 7-22 S2 demand from the Flood Loads card, when given).
    m.apply_profile(profile, flood)
    if sweep and flood is not None:                       # depth sweep: one run per d = frac · d_f
        t0 = time.time()
        seeds = ALL_SEEDS[:n_seeds]
        res = m.run_depth_sweep(sweep, seeds, generations, profile, flood)
        res["meta"] = {"engine": "moga_flood_preservation.py (NSGA-II) — depth sweep · ASCE 7-22 S2 demand from the Flood Loads card",
                       "seeds": seeds, "population_size": 50, "generations": generations, "runtime_seconds": round(time.time() - t0, 1),
                       "profile": {**profile, "demand": f"ASCE 7-22 S2 · {m.FLOOD_DEMAND.case_name}"}, "sweep_fracs": sweep, "d_f": res["d_f"]}
        return res
    profile = {"fd": m.BUILDING_PROFILE["design_flood_depth_m"], "sc": m.BUILDING_PROFILE["masonry_shear_capacity_kN"],
               "wl": m.BUILDING_PROFILE["wall_length_m"], "bh": m.BUILDING_PROFILE["basement_wall_height_m"],
               "ep": m.MODEL_PARAMS["include_earth_pressure"], "op": m.MODEL_PARAMS["include_out_of_plane"],
               "dfe": m.PH_FIXED is not None,
               "demand": (f"ASCE 7-22 S2 · {m.FLOOD_DEMAND.case_name}" if m.FLOOD_DEMAND is not None else "legacy hydrostatic + Rankine soil")}

    t0 = time.time()
    seeds = ALL_SEEDS[:n_seeds]
    winners, fronts, history = [], {}, {}
    for s in seeds:
        w, pop, hist = m.run_moga(seed=s, population_size=50, generations=generations)
        winners.append(w)
        fronts[s] = m.fast_non_dominated_sort(pop)[0]
        history[s] = [{"g": h["generation"], "st": round(h["structural"], 2), "pr": round(h["preservation"], 2), "ut": round(h["utility"], 2)} for h in hist]

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
            "engine": "moga_flood_preservation.py (NSGA-II) — live run"
                      + (" · ASCE 7-22 S2 demand from the Flood Loads card" if m.FLOOD_DEMAND is not None else ""),
            "seeds": seeds,
            "population_size": 50,
            "generations": generations,
            "runtime_seconds": round(time.time() - t0, 1),
            "profile": profile,
        },
        "points": points,
        "history": history,                                   # per-seed trajectory of the representative front point
        "seed_winners": [m.winner_record(w) for w in winners],
        "winner": {
            "strategy": consensus.intervention_strategy,
            "strategy_name": m.STRATEGY_NAMES[consensus.intervention_strategy],
            "protection_height": round(consensus.protection_height, 3),
            "visual_impact_factor": round(consensus.visual_impact_factor, 3),
            "objectives": [round(x, 2) for x in consensus.objectives],
        },
    }


def clamp_run(n_seeds, gens):
    return max(1, min(20, int(n_seeds))), max(10, min(300, int(gens)))


class Handler(SimpleHTTPRequestHandler):
    def _run_and_reply(self, n_seeds, gens, profile, flood=None, sweep=None):
        print(f"\n>>> /api/run  seeds={n_seeds} gens={gens} profile={profile}"
              + (f" flood={flood.get('caseName')} d_f={flood.get('d_f'):.2f}" if flood else " (legacy model)")
              + (f" sweep={sweep}" if sweep else ""))
        try:
            with RUN_LOCK:
                data = run_engine(n_seeds, gens, profile, flood, sweep)
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

    def do_POST(self):
        url = urlparse(self.path)
        if url.path != "/api/run":
            self.send_error(404)
            return
        n = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            self.send_error(400, "invalid JSON")
            return
        n_seeds, gens = clamp_run(req.get("seeds", 5), req.get("gens", 60))
        prof = dict(req.get("profile") or {})
        if prof.get("sc") is not None:
            prof["sc"] = max(20.0, min(400.0, float(prof["sc"])))
        flood = req.get("flood")
        if flood is not None and "params" not in flood:
            flood = None
        sweep = req.get("sweep") or None
        if sweep:
            sweep = sorted({max(0.05, min(2.0, float(x))) for x in sweep})[:12]
        self._run_and_reply(n_seeds, gens, prof, flood, sweep)

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

        n_seeds, gens = clamp_run(num("seeds", 5), num("gens", 60))
        profile = {
            "fd": max(0.5, min(4.0, num("fd", 2.5))),
            "sc": max(20.0, min(400.0, num("sc", 40.0))),
            "wl": max(0.5, min(3.0, num("wl", 2.0))),
            "bh": max(0.0, min(4.0, num("bh", 2.5))),
        }
        self._run_and_reply(n_seeds, gens, profile)


if __name__ == "__main__":
    print(f"MOGA demo server running.")
    print(f"Open:  http://localhost:{PORT}/interactive_dashboard.html")
    print("Stop with Ctrl+C.")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
