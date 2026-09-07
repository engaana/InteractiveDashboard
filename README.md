# Historic URM Building Flood-Resilience Dashboard

Interactive decision-support dashboard for selecting flood-adaptation strategies for a
historic two-story unreinforced-masonry (URM) building with basement (FEMA AE zone),
developed for **AE 540 — Final Project / Comprehensive Exam** at Penn State University.

The tool couples two engines:

| Engine | Where it runs | What it does |
|---|---|---|
| ⚡ **Dashboard JS · Live** | in the browser | Exhaustive grid search over 495 candidates (3 strategies × 15 protection heights × 11 visual-impact factors); recomputes every chart instantly on each slider change |
| 🧬 **MOGA Engine · Python** | `flood_section_module.html`, `integrate_flood_section.py`, `link_flood_loads.py` | Standalone ASCE 7-22 S2 flood-loads card, the script that injects it into the dashboard and the script that links the surrogate to it |
| `moga_flood_preservation.py` | Full NSGA-II multi-objective genetic algorithm (20 seeds × 300 generations × population 50) with Monte-Carlo scenario sampling and risk-averse aggregation |

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
pip install matplotlib
python moga_server.py
# then open http://localhost:8000/interactive_dashboard.html
```

Click **▶ RUN MOGA ENGINE** in the *3D Pareto Front — MOGA Multi-Seed* card. The local
server executes the real NSGA-II with the current Building Profile sliders and streams
fresh Pareto results back into the 3D chart (5 seeds × 60 generations ≈ 20 s).

## Repository contents

| File | Description |
|---|---|
| `interactive_dashboard.html` | Self-contained interactive dashboard (light theme, embedded MOGA results) |
| `moga_flood_preservation.py` | MOGA engine — NSGA-II, objectives, structural/preservation/utility models |
| `moga_server.py` | Local demo server exposing `/api/run` for live MOGA runs from the dashboard |
| `run_and_export.py` | Runs the full multi-seed MOGA and exports `moga_pareto_data.json` + figures |
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

---

*Ana Ferreira · Penn State University · August 2026*
