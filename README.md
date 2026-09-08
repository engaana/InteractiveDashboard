# Historic URM Building Flood-Resilience Dashboard

Interactive decision-support dashboard for selecting flood-adaptation strategies for a
historic two-story unreinforced-masonry (URM) building with basement (FEMA AE zone),
developed for **AE 540 — Final Project / Comprehensive Exam** at Penn State University.

The tool couples two engines:

| Engine | Where it runs | What it does |
|---|---|---|
| ⚡ **Dashboard JS · Live** | in the browser | Exhaustive grid search over 495 candidates (3 strategies × 15 protection heights × 11 visual-impact factors); recomputes every chart instantly on each slider change |
| 🧬 **MOGA Engine · Python** | `moga_flood_preservation.py` (+ `flood_demand.py`) | Full NSGA-II multi-objective genetic algorithm (20 seeds × 300 generations × population 50) with Monte-Carlo scenario sampling and risk-averse aggregation; since 2026-09-07 it evaluates the ASCE 7-22 S2 demand selected in the Flood Loads card |
| ⚡ **Flood Loads card** | `flood_section_module.html`, `integrate_flood_section.py`, `link_flood_loads.py` | Standalone ASCE 7-22 S2 flood-loads card, the script that injects it into the dashboard and the script that links both engines to it |

Every card in the dashboard carries a badge indicating which engine produced it.

## Flood loads card — ASCE/SEI 7-22 Supplement 2 (2026-09-06)

The card **Flood Loads — Building Cross-Section** (top of the dashboard, below the title card) computes the
nominal flood loads Fa of Chapter 5, Supplement 2, on a parametric cross-section of the building:

- **Hydrostatic** (§5.4.2): slab-on-grade case, F = ½·γw·df², or basement case (P-2345 Fig. 5B) with the
  water pressure extended to the basement floor (z) plus the submerged-soil differential (γs − γw)·hb;
  γw selectable (fresh 9.81 / salt 10.03 kN/m³), γs from ASCE 7-22 Table 3.2-1.
- **Hydrodynamic** (§5.4.3.2, Eq. 5.4-5): Fdyn = ½·ρ·Cd·V²·B·df, Cd from Table 5.4-2 (B/df) or manual.
- **Debris impact** (§5.4.5, Eq. 5.4-20): Fdi = Co·V·CR·Cs·√(ke·m), debris type (log / vehicle / vessel /
  custom) and the series stiffness of the impacted URM panel (Em, tw, L, beff, boundary condition).
- **Fa builder** (§5.5): pick any subset of the three loads (presets LC1 sustained, LC2 impact); loads are
  combined at the moment level on the panel and normalised to a DCR with a placeholder ft.

Inputs are grouped in four tabs (Site & levels · Water & soil · Hydrodynamic · Debris & panel); the
drawing, KPI strip and Fa panel react instantly. Defaults reproduce the 46 Granite St pilot
(Mathcad Rev06): Fsta 57.1 kN/m, Fdyn 84 kN, Fdi 122 kN.

The card is developed as a standalone file and injected into the dashboard:

```bash
python integrate_flood_section.py flood_section_module.html interactive_dashboard.html
python link_flood_loads.py interactive_dashboard.html
```

(idempotent — re-running replaces the previous insertion; a dated backup of the dashboard is written;
`--no-fem` builds the card without the FEM-export block).

### Link to the MOGA surrogate (2026-09-06)

`link_flood_loads.py` wires the in-browser surrogate to the card (`window.FLOOD`):

- the **structural demand** of every candidate is `FLOOD.demandAt(he)` — the Fa components selected in the
  card (hydrostatic with basement / submerged soil, hydrodynamic, debris impact), evaluated at each
  hydrograph depth `he` on a panel of tributary width `b_eff` — replacing the old ½·γ·h²·wl + Rankine earth
  pressure; the *Earth Pressure* toggle now switches the submerged-soil term (γs − γw)·hb;
- `d_f` (= SWEL_MRI − Ge), `b_eff` and `h_b` are read from the card, so the **Flood Depth, Wall Length and
  Basement H sliders were retired** (read-only chips in the top bar show the linked values and the active
  Fa case); *Shear Cap.* (range 20–400 kN, pilot placeholder 70 kN) and the model parameters remain;
- every change in the card re-renders the dashboard (`floodloads:update` event);
- **Protection to DFE** toggle (on by default): the protection height of the dry strategies is pinned to
  d_f (ASCE 24 dry floodproofing to the DFE) instead of being a free 0–3.5 m gene; switch it off to recover
  the original design space (495 candidates);
- the *Building Section (Winner)* card is drawn in the style of the Flood Loads cross-section (levels in
  ft/m, SWEL, soil, basement) with the winning strategy overlaid — barrier / sealant to the protection
  height, vents + equalised interior for wet floodproofing.

### Link to the Python MOGA engine (2026-09-07)

The same demand now drives the real NSGA-II:

- `flood_demand.py` is a Python port of the card's physics (hydrostatic with basement + submerged soil,
  hydrodynamic with Cd from Table 5.4-2, debris impact with the series stiffness k_e); `FloodDemand.demand(he,
  wl, ep, s)` reproduces `window.FLOOD.demandAt` to machine precision (checked at 22 sample points);
- `moga_flood_preservation.py` gets two hooks — `FLOOD_DEMAND` (the demand object; `None` = legacy ½γh² +
  Rankine soil, bit-identical to the original engine) and `PH_FIXED` (protection height pinned to d_f) — set
  through `apply_profile(profile, flood_state)`; the Monte-Carlo scatter of depth / shear capacity / wall
  width is now relative to the profile (same values as before at the original 2.5 m / 40 kN / 2.0 m);
- **▶ RUN MOGA ENGINE** posts the card state (`window.FLOOD.state`: all inputs + the Fa selection) and the
  toggles (shear cap., soil term, out-of-plane, PH = d_f) to `moga_server.py`, which runs the engine with
  that demand and streams the Pareto front back to the 3D chart; the GET form of `/api/run` keeps the legacy
  behaviour;
- from the command line, `run_and_export.py --flood pilot_flood_params.json --case 111 --sc 70 --dfe` runs
  the same thing (`--case` = sta/dyn/di flags: `100` hydrostatic, `110` LC1, `111` LC2; `--seeds`, `--gens`,
  `--tag`, `--outdir` for quick tagged runs). `pilot_flood_params.json` is the card state at the Old Labor
  Hall pilot; `pilot_runs/` holds the tagged runs listed under *Headline results*.

### Depth sweep — at which depth does the winner flip? (2026-09-08)

Pinning the protection height to d_f leaves the optimizer with one continuous gene (VIF), so the Pareto
front of a single run is thin. Instead of re-freeing PH (which brings back overtopped barriers), the engine
can **sweep the flood depth**: `run_depth_sweep()` runs the MOGA at d = frac · d_f (¼, ½, ¾, 1, 1¼ … — PH
pinned to d in each run, demand from the card physics at that depth) and reports one consensus winner per
depth plus the *tipping depth* — the first depth won by wet floodproofing. In the dashboard, choose a sweep
in the selector next to **▶ RUN MOGA ENGINE**: the 3D chart sizes the points by depth and stars the winner
of every depth, and a strip of chips shows Fa (with the debris share) and the winner per depth. From the
command line: `run_and_export.py --flood pilot_flood_params.json --case 111 --sc 70 --depth-sweep
0.25,0.5,0.75,1,1.25 --seeds 5 --gens 60 --tag pilot_LC2 --outdir pilot_runs`.

## Strategies and objectives

Three intervention strategies — **S0** dry floodproofing (sealant/coating), **S1** dry
floodproofing (removable barrier), **S2** wet floodproofing (hydrostatic vents) — are
evaluated against three objectives: **Structural** safety (hydrostatic + earth pressure vs
shear and out-of-plane capacity), **Preservation** (NPS-based sub-scores: reversibility,
compatibility, distinguishability, moisture, fenestration), and functional **Utility**
(immediate usability, recovery time, lifecycle cost). The composite score is the
*minimum* of the three objectives.

## Quick start

Open `interactive_dashboard.html` in any browser — it is fully self-contained (the
results of the full MOGA run are embedded in the file).

### Live MOGA runs (demo mode)

```bash
python moga_server.py            # standard library only; pip install matplotlib for the engine figures
# then open http://localhost:8000/interactive_dashboard.html
```

Click **▶ RUN MOGA ENGINE** in the *3D Pareto Front — MOGA Multi-Seed* card. The local
server executes the real NSGA-II with the current Building Profile (d_f, b_eff, h_b and the Fa case from
the Flood Loads card; shear cap. and toggles from the top bar) and streams fresh Pareto results back into
the 3D chart (5 seeds × 60 generations ≈ 20 s).

## Repository contents

| File | Description |
|---|---|
| `interactive_dashboard.html` | Self-contained interactive dashboard (light theme, embedded MOGA results) |
| `moga_flood_preservation.py` | MOGA engine — NSGA-II, objectives, structural/preservation/utility models |
| `flood_demand.py` | ASCE 7-22 S2 flood demand for the engine — Python port of the Flood Loads card physics |
| `moga_server.py` | Local demo server exposing `/api/run` for live MOGA runs from the dashboard (POST = card demand, GET = legacy) |
| `run_and_export.py` | Runs the multi-seed MOGA and exports `moga_pareto_data.json` + figures (options: `--flood`, `--case`, `--sc`, `--dfe`, `--seeds`, `--gens`, `--tag`, `--outdir`) |
| `pilot_flood_params.json` | `window.FLOOD.state` of the card at the Old Labor Hall pilot (46 Granite St, Barre VT) |
| `pilot_runs/` | Tagged engine runs at the pilot (hydrostatic / LC1 / LC2, PH = d_f; LC2 with the free PH gene; full 20 × 300 LC2 run) |
| `moga_pareto_data.json` | 999 Pareto-front points + consensus winner from the full run (2026-08-19) |
| `visualizations/` | Figures generated by the engine (convergence, Pareto fronts, spatial grids) |
| `consultant_report_latest.txt`, `run_output_v3.txt` | Report and log of the full run |
| `demo_apresentacao.md` | Presentation-day runbook (PT-BR) |
| `AE540_Dashboard_Presentation.pptx` | Committee presentation slides |

## Headline results

At the design condition (flood depth 2.5 m, shear capacity 40 kN) the multi-seed
consensus winner is **S1 — removable barrier** (PH 0.73 m, VIF 0.55; objectives
50 / 79 / 47). Under extreme scenarios (e.g. flood depth 4.0 m, shear capacity 20 kN,
overtopping 0.70) every dry-floodproofing design fails structurally and the optimizer
switches to **S2 — hydrostatic vents**, preferring pressure equalization over resistance.
S0 (sealant/coating) is dominated almost everywhere on the Pareto front, echoing NPS
Standard 9 concerns about irreversible moisture damage.

### Pilot with the ASCE 7-22 S2 loads (2026-09-07)

Old Labor Hall, 46 Granite St, Barre VT — d_f = SWEL_MRI − Ge = 2.15 m, basement (h_b = 1.22 m), b_eff = 1.0 m,
shear cap. 70 kN (placeholder), PH pinned to d_f, engine runs of 5 seeds × 60 generations (`pilot_runs/`):

| Fa case in the card | Demand at d_f | Consensus winner | Objectives (St / Pr / Ut) |
|---|---|---|---|
| Hydrostatic only (`100`) | 57.1 kN/m | **S1 removable barrier** to d_f | 41.4 / 97.5 / 92.7 |
| LC1 hydrostatic + hydrodynamic (`110`) | 61.7 kN/m | **S1 removable barrier** to d_f | 36.0 / 95.7 / 92.7 |
| LC2 = LC1 + debris impact (`111`) | 184.1 kN/m | **S2 wet floodproofing** — every dry design fails structurally | 97.6 / 89.9 / 11.0 |
| LC2, protection height free (no `--dfe`) | — | S1 barrier of 0.60 m — "works" only because it is overtopped | 55.5 / 97.5 / 51.4 |
| LC2, full run 20 seeds × 300 generations | 184.1 kN/m | **S2 wet floodproofing** in all 20 seeds (209 Pareto points, 337 s) | 97.7 / 89.9 / 11.0 |

The real NSGA-II therefore reproduces the in-browser surrogate: the winner flips from dry to wet
floodproofing the moment debris impact (Eq. 5.4-20, ≈ 2/3 of the LC2 demand) is included — consistent with
FEMA P-936's 3-ft practical limit for dry floodproofing (d_f ≈ 7 ft here).

**Depth sweep, LC2** (`pilot_runs/moga_depth_sweep_pilot_LC2.json`, 5 seeds × 60 generations per depth):

| d (m) | d/d_f | Fa (kN) | of which debris | Winner | St / Pr / Ut |
|---|---|---|---|---|---|
| 0.27 | ⅛ | 13.1 | 0 | S1 barrier | 84.8 / 97.4 / 93.0 |
| 0.54 | ¼ | 17.9 | 0 | S1 barrier | 79.3 / 96.7 / 92.9 |
| 0.81 | ⅜ | 23.4 | 0 | S1 barrier | 73.1 / 96.9 / 92.9 |
| 1.07 | ½ | 107.3 | 77.7 | S1 barrier | 38.3 / 94.6 / 92.8 |
| 1.34 | ⅝ | 141.2 | 104.7 | S1 barrier (near tie) | 15.2 / 96.1 / 89.7 |
| 1.61 | ¾ | 166.6 | 122.4 | S1 barrier (near tie) | 11.9 / 97.3 / 89.5 |
| 1.88 | ⅞ | 175.0 | 122.4 | **S2 wet** | 97.2 / 89.8 / 11.2 |
| 2.15 | 1 | 184.1 | 122.4 | **S2 wet** | 97.7 / 86.9 / 11.0 |
| 2.69 | 1¼ | 204.4 | 122.4 | **S2 wet** | 97.5 / 60.2 / 11.0 |

Reading: below 0.91 m (3 ft, §5.3.9 debris threshold) the dry strategies are comfortable; the debris term
appears at 1.07 m and takes ≈ 70 % of the demand; between 1.3 and 1.9 m the call is a near tie — the barrier's
robust structural score (12–15, i.e. the wall fails in most Monte-Carlo scenarios) is barely above the wet
strategy's utility floor (11) — and from ≈ 1.9 m wet floodproofing wins outright. The deterministic
demand exceeds the out-of-plane cap (135 kN) from ≈ 1.3 m. For S2 the composite is bounded by utility (11),
so its VIF / preservation value is not informative.

---

*Ana Ferreira · Penn State University · August 2026*
