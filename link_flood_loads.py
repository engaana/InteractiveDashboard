#!/usr/bin/env python3
"""
Link the MOGA surrogate of interactive_dashboard.html to the Flood Loads card (window.FLOOD).

- Top bar: Flood Depth, Wall Length and Basement H sliders → read-only chips fed by the card
  (d_f = SWEL_MRI − Ge, b_eff, h_b) plus the active Fa case; Shear Cap. and model parameters stay.
- I(): fd / wl / bh come from FLOOD.state.
- oStruct(): the panel demand is FLOOD.demandAt(he) — the loads selected in the Fa builder
  (hydrostatic with basement / submerged soil, hydrodynamic, debris) — instead of ½γh²·wl + Rankine earth pressure.
- baseline(): same demand at the design depth.
- The dashboard re-renders on every change of the card ('floodloads:update').
- v4: ▶ RUN MOGA ENGINE posts the card state (window.FLOOD.state: inputs + Fa selection) and the
  profile flags (shear cap., soil term, out-of-plane, PH pinned to d_f) to moga_server.py, so the real
  NSGA-II (moga_flood_preservation.py + flood_demand.py) runs with the same ASCE 7-22 S2 demand.
- v5: depth sweep — ▶ RUN can run the engine at d = frac · d_f (PH pinned to d in each run); the 3D chart
  sizes the points by depth and stars the winner of every depth; a strip of chips shows Fa and the winner
  per depth and the tipping depth (first depth won by wet floodproofing).
Idempotent: guarded by the LINK markers (v3 → v4 → v5 on an already-linked file). Run AFTER integrate_flood_section.py.
usage: python3 link_flood_loads.py interactive_dashboard.html
"""
import sys, re, shutil, datetime

MARK = '/* FLOOD-LINK v3 */'
MARK4 = '/* FLOOD-LINK v4 */'
MARK5 = '/* FLOOD-LINK v5 */'


DRAW_SECTION = r"""        function drawSection(w, inp) {
            // Winner cross-section, drawn like the Flood Loads card (levels, water, soil, pressure side) with the
            // winning strategy overlaid: barrier / sealant to the protection height, vents + interior water for wet FP.
            const c = document.getElementById('secC'), x = c.getContext('2d');
            const W = c.width, H = c.height; x.clearRect(0, 0, W, H);
            const FT = 0.3048, FS = window.FLOOD && window.FLOOD.state;
            const lv = FS ? FS.levels : { Ge: 0, SWEL: inp.fd, FFE: 1.6, ELb: -inp.bh, roof: 8.0, n: 2, hs: 3.2, bs: true };
            const base = lv.bs ? lv.ELb : lv.Ge, s = w.s, ph = w.ph, fd = inp.fd;
            const yLo = Math.min(base, lv.Ge) - 0.9, yHi = Math.max(lv.roof, lv.SWEL) + 0.7;
            const top = 16, bot = H - 14, sy = (bot - top) / (yHi - yLo), Y = e => bot - (e - yLo) * sy;
            const xL = 215, xR = W - 150, yGe = Y(lv.Ge), yB = Y(base), ySW = Y(lv.SWEL), yRf = Y(lv.roof);
            const ftm = e => (e / FT).toFixed(1) + ' ft · ' + e.toFixed(2) + ' m';
            // soil, flood water outside (flood-facing side), saturated band
            x.fillStyle = '#f5efe4'; x.fillRect(0, yGe, W, H - yGe);
            x.fillStyle = 'rgba(2,132,199,.16)'; x.fillRect(0, ySW, xL, yGe - ySW);
            if (lv.bs) { x.fillStyle = 'rgba(2,132,199,.08)'; x.fillRect(0, yGe, xL, yB - yGe) }
            // building
            x.fillStyle = '#fff'; x.fillRect(xL, yRf, xR - xL, yB - yRf);
            x.strokeStyle = '#334155'; x.lineWidth = 2; x.strokeRect(xL, yRf, xR - xL, yB - yRf);
            x.fillStyle = '#cbd5e1'; x.fillRect(xL, yRf, 8, yB - yRf); x.fillRect(xR - 8, yRf, 8, yB - yRf);
            // interior water (leakage / wet floodproofing) — from the lowest floor up
            const ip = leak(s, fd, ph, inp.br, inp.bf);
            if (ip > .03) { const y0 = Y(base), y1 = Y(Math.min(lv.Ge + ip, lv.roof));   // interior head measured from grade, filling the basement first
                x.fillStyle = s === 2 ? 'rgba(5,150,105,.12)' : 'rgba(2,132,199,.08)'; x.fillRect(xL + 8, y1, xR - xL - 16, y0 - y1);
                x.fillStyle = s === 2 ? SC[2] : 'rgba(2,132,199,.8)'; x.font = '500 9px Inter'; x.textAlign = 'center';
                x.fillText((s === 2 ? 'equalised interior ' : 'leakage ') + ip.toFixed(2) + ' m', (xL + xR) / 2, y1 - 4) }
            // floor levels + labels (right)
            const levels = []; if (lv.bs) levels.push(['Basement', lv.ELb]);
            for (let i = 0; i < lv.n; i++) levels.push([i === 0 ? '1st floor' : i === 1 ? '2nd floor' : i === 2 ? '3rd floor' : (i + 1) + 'th floor', lv.FFE + i * lv.hs]);
            levels.push(['Roof', lv.roof]);
            for (const [nm, e] of levels) { const y = Y(e);
                x.strokeStyle = '#334155'; x.lineWidth = 2.5; x.beginPath(); x.moveTo(xL, y); x.lineTo(xR, y); x.stroke();
                x.strokeStyle = '#94a3b8'; x.lineWidth = 1; x.setLineDash([5, 4]); x.beginPath(); x.moveTo(xR + 6, y); x.lineTo(W - 6, y); x.stroke(); x.setLineDash([]);
                x.fillStyle = '#0f172a'; x.font = '600 10px Inter'; x.textAlign = 'left'; x.fillText(nm, xR + 12, y - 4);
                x.fillStyle = '#64748b'; x.font = '500 8.5px Inter'; x.fillText(ftm(e), xR + 12, y + 11) }
            // windows
            x.fillStyle = '#e2e8f0'; x.strokeStyle = '#94a3b8'; x.lineWidth = 1;
            for (let i = 0; i < lv.n; i++) { const yTop = Y(lv.FFE + i * lv.hs + 0.9), h = Math.min(1.5, lv.hs - 1.3) * sy;
                for (let k = 0; k < 4; k++) { const wx = xL + 30 + k * (xR - xL - 60) / 3 - 7; x.fillRect(wx, yTop - h, 14, h); x.strokeRect(wx, yTop - h, 14, h) } }
            // ground and SWEL lines + labels (left)
            x.strokeStyle = '#78350f'; x.lineWidth = 1.5; x.beginPath(); x.moveTo(0, yGe); x.lineTo(xL, yGe); x.moveTo(xR, yGe); x.lineTo(W, yGe); x.stroke();
            x.strokeStyle = '#0284c7'; x.lineWidth = 1.5; x.setLineDash([7, 4]); x.beginPath(); x.moveTo(0, ySW); x.lineTo(xL, ySW); x.stroke(); x.setLineDash([]);
            x.fillStyle = '#0f172a'; x.font = '600 10px Inter'; x.textAlign = 'left';
            x.fillText('SWEL MRI  ' + (lv.SWEL / FT).toFixed(2) + ' ft', 6, ySW - 5);
            x.fillStyle = '#64748b'; x.font = '500 9px Inter'; x.fillText('d_f = ' + fd.toFixed(2) + ' m above grade', 6, ySW + 12);
            x.fillStyle = '#0f172a'; x.font = '600 10px Inter'; x.fillText('Ge  ' + (lv.Ge / FT).toFixed(1) + ' ft', 6, yGe - 5);
            if (lv.bs) { x.fillStyle = '#a16207'; x.font = '500 9px Inter'; x.fillText('h_b = ' + (lv.Ge - lv.ELb).toFixed(2) + ' m', 6, yB - 5) }
            // winning strategy overlay
            const yP = Y(lv.Ge + Math.min(ph, lv.roof - lv.Ge));
            x.font = '700 10px Inter'; x.textAlign = 'right';
            if (s === 0) {          // sealant / coating on the wall faces up to PH
                x.fillStyle = SC[0]; x.fillRect(xL - 4, yP, 6, yGe - yP); x.fillRect(xR - 2, yP, 6, yGe - yP);
                x.fillText('Sealant to ' + ph.toFixed(2) + ' m', xL - 10, yP - 4);
            } else if (s === 1) {   // removable barrier in front of the flood-facing wall
                x.fillStyle = 'rgba(2,132,199,.28)'; x.fillRect(xL - 22, yP, 18, yGe - yP);
                x.strokeStyle = SC[1]; x.lineWidth = 2; x.strokeRect(xL - 22, yP, 18, yGe - yP);
                x.fillStyle = SC[1]; x.fillText('Barrier h = ' + ph.toFixed(2) + ' m', xL - 28, yP - 4);
            } else {                // wet floodproofing: hydrostatic vents at the wall base
                x.fillStyle = SC[2];
                for (let k = 0; k < 6; k++) { const vx = xL + 20 + k * (xR - xL - 40) / 5; x.beginPath(); x.arc(vx, Y(base) - 6, 3.5, 0, Math.PI * 2); x.fill() }
                x.textAlign = 'center'; x.fillText('Hydrostatic vents (§60.3 openings)', (xL + xR) / 2, Y(base) - 14);
            }
            // title
            x.fillStyle = '#0f172a'; x.font = '600 10px Inter'; x.textAlign = 'center';
            x.fillText('Winner: S' + s + ' · ' + SN[s] + (lv.bs ? (s === 2 ? ' · basement flooded (equalised)' : ' · basement (water excluded)') : ' · slab on grade'), W / 2, 12);
        }"""


def sub1(s, old, new, label):
    assert old in s, f'anchor not found: {label}'
    return s.replace(old, new, 1)


def link_v4(s):
    """Live MOGA run: send the Flood Loads card state to the server (POST) instead of the retired sliders."""
    s = sub1(s, "            const url = `/api/run?seeds=${seeds}&gens=${gens}&fd=${inp.fd}&sc=${inp.sc}&wl=${inp.wl}&bh=${inp.bh}`;\n",
             "            const url = `/api/run?seeds=${seeds}&gens=${gens}&fd=${inp.fd}&sc=${inp.sc}&wl=${inp.wl}&bh=${inp.bh}`;\n"
             "            const FS = window.FLOOD && window.FLOOD.state;   " + MARK4 + "\n"
             "            // with the card present: POST its full state (inputs + Fa selection) and the profile flags → ASCE 7-22 S2 demand in the engine\n"
             "            const req = FS ? { method: 'POST', headers: { 'Content-Type': 'application/json' },\n"
             "                               body: JSON.stringify({ seeds: +seeds, gens: +gens, profile: { sc: inp.sc, ep: inp.ep, op: inp.op, dfe: inp.dfe }, flood: FS }) } : undefined;\n", 'live-run url')
    s = sub1(s, "            mogaStatus.textContent = `Running NSGA-II (${seeds} seeds × ${gens} gens, pop 50)… watch progress in the terminal`;",
             "            mogaStatus.textContent = `Running NSGA-II (${seeds} seeds × ${gens} gens, pop 50) · ${FS ? FS.caseName + ' · Fa ' + FS.Fa.toFixed(1) + ' kN/m' + (inp.dfe ? ' · PH = d_f' : '') : 'legacy model'}… watch progress in the terminal`;", 'live-run status')
    s = sub1(s, "                const r = await fetch(url);", "                const r = await fetch(url, req);", 'live-run fetch')
    s = sub1(s, "values (d_f, b_eff and h_b from the Flood Loads card, shear cap. slider)",
             "values (d_f, b_eff, h_b and the selected F<sub>a</sub> case from the Flood Loads card; shear cap., soil term, out-of-plane and PH-to-DFE toggles)", 'live-run text')
    return s


SWEEP_JS = r"""
            // depth sweep results: chips per depth + tipping depth   """ + MARK5 + r"""
            const strip = document.getElementById('sweepStrip');
            if (d.sweep) {
                const SCc = { 0: '#c44e52', 1: '#4c72b0', 2: '#55a868' };
                strip.style.display = 'flex';
                strip.innerHTML = d.sweep.map(r => `<div style="border:1px solid ${SCc[r.winner.strategy]};border-left:4px solid ${SCc[r.winner.strategy]};border-radius:8px;padding:5px 9px;font:500 10.5px Inter;color:var(--muted);background:var(--card);min-width:118px">` +
                    `<div style="font:700 11.5px Inter;color:var(--ink)">d = ${r.d.toFixed(2)} m <span style="color:var(--dim);font-weight:500">(${r.frac}·d_f)</span></div>` +
                    `<div>F<sub>a</sub> ${r.Fa.toFixed(1)} kN · di ${r.Fa_parts.di.toFixed(0)}</div>` +
                    `<div style="color:${SCc[r.winner.strategy]};font-weight:700">S${r.winner.strategy} ${r.winner.strategy === 2 ? 'wet' : r.winner.strategy === 1 ? 'barrier' : 'sealant'} · ${r.winner.objectives.map(x => x.toFixed(0)).join(' / ')}</div></div>`).join('') +
                    `<div style="align-self:center;font:700 11px Inter;color:${d.tipping_depth ? '#15803d' : 'var(--muted)'};padding:4px 8px">${d.tipping_depth ? '⇢ dry → wet from d ≥ ' + d.tipping_depth.toFixed(2) + ' m (' + (d.tipping_depth / 0.3048).toFixed(1) + ' ft)' : 'no flip to wet floodproofing in this range'}</div>`;
            } else { strip.style.display = 'none'; strip.innerHTML = ''; }
"""


def link_v5(s):
    """Depth sweep: run the engine at several fractions of d_f and show the winner per depth."""
    s = sub1(s, "                    <span id=\"mogaStatus\" class=\"sub\" style=\"font-size:.72rem\"></span>\n                </div>\n",
             "                    <select id=\"selSweep\" title=\"Depth sweep: run the engine at d = frac · d_f, protection height pinned to d in each run\"\n"
             "                        style=\"border:1px solid var(--border);border-radius:8px;padding:6px 8px;font:600 11px Inter;color:var(--muted);background:var(--card)\">\n"
             "                        <option value=\"\" selected>single run at d_f</option>\n"
             "                        <option value=\"0.25,0.5,0.75,1\">sweep d_f · 4 depths (¼ … 1)</option>\n"
             "                        <option value=\"0.25,0.5,0.75,1,1.25\">sweep d_f · 5 depths (¼ … 1¼)</option>\n"
             "                        <option value=\"0.125,0.25,0.375,0.5,0.625,0.75,0.875,1,1.25\">sweep d_f · 9 depths (⅛ … 1¼)</option>\n"
             "                    </select>\n"
             "                    <span id=\"mogaStatus\" class=\"sub\" style=\"font-size:.72rem\"></span>\n                </div>\n"
             "                <div id=\"sweepStrip\" style=\"display:none;flex-wrap:wrap;gap:6px;margin-bottom:8px\"></div>\n", 'sweep select')
    s = sub1(s, "            const req = FS ? { method: 'POST', headers: { 'Content-Type': 'application/json' },\n"
                "                               body: JSON.stringify({ seeds: +seeds, gens: +gens, profile: { sc: inp.sc, ep: inp.ep, op: inp.op, dfe: inp.dfe }, flood: FS }) } : undefined;\n",
             "            const sweepSel = document.getElementById('selSweep').value, sweep = (FS && sweepSel) ? sweepSel.split(',').map(Number) : null;   " + MARK5 + "\n"
             "            const req = FS ? { method: 'POST', headers: { 'Content-Type': 'application/json' },\n"
             "                               body: JSON.stringify({ seeds: +seeds, gens: +gens, profile: { sc: inp.sc, ep: inp.ep, op: inp.op, dfe: inp.dfe }, flood: FS, sweep }) } : undefined;\n", 'sweep request')
    s = sub1(s, "            mogaStatus.textContent = `Running NSGA-II (${seeds} seeds × ${gens} gens, pop 50) · ${FS ? FS.caseName",
             "            mogaStatus.textContent = `Running NSGA-II (${seeds} seeds × ${gens} gens, pop 50${sweep ? ' × ' + sweep.length + ' depths' : ''}) · ${FS ? FS.caseName", 'sweep status')
    s = sub1(s, "                mogaData = d; drawMoga3D();\n                const w = d.winner;\n",
             "                mogaData = d; drawMoga3D();\n                const w = d.winner;\n" + SWEEP_JS, 'sweep chips')
    s = sub1(s, "                mogaStatus.textContent = `✓ Done in ${d.meta.runtime_seconds}s · ${d.points.length} Pareto points · winner S${w.strategy}",
             "                mogaStatus.textContent = `✓ Done in ${d.meta.runtime_seconds}s · ${d.points.length} Pareto points${d.sweep ? ' over ' + d.sweep.length + ' depths · at d_f:' : ' ·'} winner S${w.strategy}", 'sweep done text')
    # 3D chart (drawMoga3D only — draw3DPareto shares the same legend code): point size by depth, one star per depth
    head, s = s[:s.index('        function drawMoga3D() {')], s[s.index('        function drawMoga3D() {'):]
    s = sub1(s, "                return { ...pp, s: p.s, st: p.st, pr: p.pr, ut: p.ut };\n            });",
             "                return { ...pp, s: p.s, st: p.st, pr: p.pr, ut: p.ut, d: p.d };\n            });\n"
             "            const dRef = (mogaData.meta && mogaData.meta.d_f) || 1;   " + MARK5 + " // point radius grows with the depth of its run", '3D projected')
    s = sub1(s, "                ctx.beginPath(); ctx.arc(p.sx, p.sy, 3, 0, Math.PI * 2);\n                ctx.fillStyle = SC[p.s]; ctx.globalAlpha = 0.45; ctx.fill();",
             "                ctx.beginPath(); ctx.arc(p.sx, p.sy, p.d != null ? 1.5 + 3.5 * Math.min(p.d / dRef, 1.3) : 3, 0, Math.PI * 2);\n                ctx.fillStyle = SC[p.s]; ctx.globalAlpha = p.d != null ? 0.35 : 0.45; ctx.fill();", '3D radius')
    s = sub1(s, "            // Legend\n            ctx.font = '500 10px Inter'; ctx.textAlign = 'left'; ctx.globalAlpha = 1;",
             "            // depth-sweep winners: a small star per depth, labelled with d\n"
             "            if (mogaData.sweep) for (const r of mogaData.sweep) {\n"
             "                const o = r.winner.objectives, q = projectM(o[0]/100*50-25, o[1]/100*50-25, o[2]/100*50-25, cx, cy, scale);\n"
             "                drawStar(ctx, q.sx, q.sy, 5, 6, 3); ctx.fillStyle = SC[r.winner.strategy]; ctx.globalAlpha = 0.9; ctx.fill(); ctx.strokeStyle = '#0f172a'; ctx.lineWidth = 0.8; ctx.stroke(); ctx.globalAlpha = 1;\n"
             "                ctx.font = '600 9px Inter'; ctx.fillStyle = '#334155'; ctx.textAlign = 'left'; ctx.fillText(r.d.toFixed(2) + ' m → S' + r.winner.strategy, q.sx + 8, q.sy - 4);\n"
             "            }\n"
             "            // Legend\n            ctx.font = '500 10px Inter'; ctx.textAlign = 'left'; ctx.globalAlpha = 1;", '3D sweep stars')
    s = sub1(s, "            ctx.fillText(pts.length + ' Pareto-front points across ' + nSeeds + ' seeds', W - 16, H - 10);",
             "            ctx.fillText(pts.length + ' Pareto-front points across ' + nSeeds + ' seeds' + (mogaData.sweep ? ' × ' + mogaData.sweep.length + ' depths (point size ∝ d)' : ''), W - 16, H - 10);", '3D count label')
    return head + s


def link(path):
    s = open(path, encoding='utf-8').read()
    if MARK in s:
        if MARK5 in s:
            print('already linked'); return
        if MARK4 not in s: s = link_v4(s)
        s = link_v5(s); open(path, 'w', encoding='utf-8').write(s); print('linked v4/v5', path); return
    shutil.copy(path, path.replace('.html', f'_prelink_{datetime.date.today():%Y%m%d}.html'))

    # ---- top bar -------------------------------------------------------------------------------
    chip = lambda label, vid: (f'<div class="cg"><label>{label}</label>\n'
                               f'                    <div class="sw"><span class="sv" id="{vid}" style="min-width:0;text-align:left">—</span></div>\n'
                               f'                </div>')
    s = sub1(s, re.search(r'<div class="cg"><label>Flood Depth</label>.*?</div>\n\s*</div>', s, re.S).group(0),
             chip('d<sub>f</sub> · SWEL<sub>MRI</sub> − G<sub>e</sub>', 'vFD'), 'Flood Depth block')
    s = sub1(s, re.search(r'<div class="cg"><label>Wall Length</label>.*?</div>\n\s*</div>', s, re.S).group(0),
             chip('Wall width b<sub>eff</sub>', 'vWL'), 'Wall Length block')
    s = sub1(s, re.search(r'<div class="cg"><label>Basement H</label>.*?</div>\n\s*</div>', s, re.S).group(0),
             chip('Basement h<sub>b</sub>', 'vBH') + '\n                ' + chip('F<sub>a</sub> case', 'vFA'), 'Basement H block')
    s = sub1(s, '<div class="ctrl-section-title">Building Profile</div>',
             '<div class="ctrl-section-title">Building Profile · <span style="color:var(--green)">linked to the Flood Loads card ↓</span></div>', 'section title')
    s = sub1(s, re.search(r'class="tgl-label">Earth Pressure</span>', s).group(0),
             'class="tgl-label">Soil term (γs−γw)·h<sub>b</sub></span>', 'earth-pressure label')
    # shear-capacity range: the code-exact loads are larger than the old ½γh² surrogate
    s = sub1(s, '<input type="range" id="rSC" min="20" max="60" step="1" value="40" />',
             '<input type="range" id="rSC" min="20" max="400" step="1" value="70" />', 'shear slider')   # pilot placeholder: v_te 0.2 MPa × t_w 0.35 m × b_eff 1.0 m ≈ 70 kN (ASCE 41 URM lower-bound bed-joint shear)

    # ---- inputs --------------------------------------------------------------------------------
    s = sub1(s, "                fd: +document.getElementById('rFD').value,",
             "                fd: window.FLOOD && window.FLOOD.state ? window.FLOOD.state.d_f : 2.5,   " + MARK, 'I() fd')
    s = sub1(s, "                wl: +document.getElementById('rWL').value,",
             "                wl: window.FLOOD && window.FLOOD.state ? window.FLOOD.state.b_eff : 2,", 'I() wl')
    s = sub1(s, "                bh: +document.getElementById('rBH').value,",
             "                bh: window.FLOOD && window.FLOOD.state ? window.FLOOD.state.h_b : 2.5,", 'I() bh')

    # ---- structural demand ---------------------------------------------------------------------
    s = sub1(s, "                let f = hForce(he, inp.wl, g);\n                if (inp.ep) f += ePress(Math.min(inp.bh, he), inp.wl, gs, k0);",
             "                // demand from the Flood Loads card (selected Fa components) — fallback: legacy ½γh² + Rankine soil\n"
             "                let f = window.FLOOD && window.FLOOD.state ? window.FLOOD.demandAt(he, { wl: inp.wl, ep: inp.ep, s }).total\n"
             "                      : hForce(he, inp.wl, g) + (inp.ep ? ePress(Math.min(inp.bh, he), inp.wl, gs, k0) : 0);", 'oStruct demand')
    s = sub1(s, "            const f = hForce(inp.fd, inp.wl, 9.81);",
             "            const f = window.FLOOD && window.FLOOD.state ? window.FLOOD.demandAt(inp.fd, { wl: inp.wl, ep: inp.ep, s: -1 }).total : hForce(inp.fd, inp.wl, 9.81);", 'baseline')

    # ---- value displays ------------------------------------------------------------------------
    s = sub1(s, "            document.getElementById('vBH').textContent = inp.bh.toFixed(1) + ' m';",
             "            document.getElementById('vBH').textContent = inp.bh.toFixed(2) + ' m';\n"
             "            if (window.FLOOD && window.FLOOD.state) { const fs = window.FLOOD.state; document.getElementById('vFA').textContent = fs.caseName + ' · ' + fs.Fa.toFixed(1) + ' kN/m'; }", 'vBH display')


    # ---- protection height pinned to the design flood depth (dry floodproofing to the DFE) -----
    s = sub1(s, re.search(r'class="tgl-label">Out-of-Plane</span>', s).group(0),
             'class="tgl-label">Out-of-Plane</span>\n'
             '                    <label class="toggle"><input type="checkbox" id="tPH" checked /><span></span></label><span\n'
             '                        class="tgl-label">Protection to DFE (PH = d<sub>f</sub>)</span>', 'PH toggle')
    s = sub1(s, "                op: document.getElementById('tOP').checked\n",
             "                op: document.getElementById('tOP').checked,\n                dfe: document.getElementById('tPH').checked\n", 'I() dfe')
    s = sub1(s, "        function cl(v, lo, hi) { return Math.max(lo, Math.min(hi, v)) }",
             "        function cl(v, lo, hi) { return Math.max(lo, Math.min(hi, v)) }\n"
             "        // protection-height design space: pinned to d_f (ASCE 24 dry floodproofing to the DFE) or the free 0–3.5 m gene\n"
             "        function phGrid(inp) { if (inp.dfe) return [+inp.fd.toFixed(2)]; const a = []; for (let p = 0; p <= 3.5; p += .25) a.push(+p.toFixed(2)); return a; }", 'phGrid')
    s = sub1(s, "            const PHS = []; for (let p = 0; p <= 3.5; p += .25)PHS.push(+p.toFixed(2));",
             "            const PHS = phGrid(inp);", 'gridSearch PHS')
    s = sub1(s, "                    for (let ph = 0; ph <= 3.5; ph += .5)for (let vif = 0; vif <= 1; vif += .2) {",
             "                    for (const ph of (ti.dfe ? phGrid(ti) : [0, .5, 1, 1.5, 2, 2.5, 3, 3.5])) for (let vif = 0; vif <= 1; vif += .2) {", 'sensitivity PH loop')
    s = sub1(s, "            const PHS2=[];for(let p=0;p<=3.5;p+=.25)PHS2.push(+p.toFixed(2));",
             "            const PHS2=phGrid(inp);", 'parcoords PHS2')
    s = sub1(s, "            const PHS3 = []; for (let p = 0; p <= 3.5; p += .25) PHS3.push(+p.toFixed(2));",
             "            const PHS3 = phGrid(inp);", '3D PHS3')
    s = sub1(s, '<div class="ks">Best design gene</div>', '<div class="ks" id="kPHs">Best design gene</div>', 'kPH caption')
    s = sub1(s, "            document.getElementById('kPH').textContent = wi.ph.toFixed(2) + ' m';",
             "            document.getElementById('kPH').textContent = wi.ph.toFixed(2) + ' m';\n"
             "            document.getElementById('kPHs').textContent = inp.dfe ? 'pinned to d_f — dry floodproofing to the DFE' : 'Best design gene';", 'kPH text')
    # dashboard listeners: only the top bar (the card drives the dashboard through its own event)
    s = sub1(s, "        document.querySelectorAll('input[type=range]').forEach(el => el.addEventListener('input', update));\n"
                "        document.querySelectorAll('input[type=checkbox]').forEach(el => el.addEventListener('change', update));",
             "        document.querySelectorAll('.ctrl-bar input[type=range]').forEach(el => el.addEventListener('input', update));\n"
             "        document.querySelectorAll('.ctrl-bar input[type=checkbox]').forEach(el => el.addEventListener('change', update));", 'listeners')

    # ---- Building Section (Winner): redraw in the style of the Flood Loads cross-section ------
    a = s.index('        function drawSection(w, inp) {'); b = s.index('        function drawSensitivity(inp) {')
    s = s[:a] + DRAW_SECTION + '\n' + s[b:]

    # tie-break equal composites (min-aggregation) by the sum of the three objectives
    s = sub1(s, "            const wi = res.reduce((a, b) => a.comp >= b.comp ? a : b);",
             "            const wi = res.reduce((a, b) => (a.comp > b.comp || (a.comp === b.comp && a.st + a.pr + a.ut >= b.st + b.pr + b.ut)) ? a : b);   // tie-break by objective sum", 'winner tie-break')

    # ---- events --------------------------------------------------------------------------------
    s = sub1(s, "        update();\n    </script>",
             "        window.addEventListener('floodloads:update', update);   // re-render when the Flood Loads card changes\n        update();\n    </script>", 'init')

    # ---- texts ---------------------------------------------------------------------------------
    m = re.search(r'sliders \(flood depth, shear cap\., wall\s+length, basement H\)', s); assert m, 'live-run text'
    s = s.replace(m.group(0), "values (d_f, b_eff and h_b from the Flood Loads card, shear cap. slider)", 1)
    s = sub1(s, '<span><span class="src-badge src-moga">🧬 MOGA Engine · Python</span>',
             '<span><span class="src-badge src-js">⚡ Flood Loads card</span>&nbsp; the structural demand of the surrogate is the '
             '<strong style="color:var(--ink)">F<sub>a</sub> selected in the Flood Loads card</strong> (ASCE 7-22 S2 hydrostatic / hydrodynamic / debris), '
             'evaluated at each hydrograph depth; d<sub>f</sub>, b<sub>eff</sub> and h<sub>b</sub> are read from it — the Flood Depth, Wall Length and Basement H sliders were retired.</span>\n'
             '                <span><span class="src-badge src-moga">🧬 MOGA Engine · Python</span>', 'src-note')
    s = link_v4(s)
    s = link_v5(s)
    open(path, 'w', encoding='utf-8').write(s)
    print('linked', path)


if __name__ == '__main__':
    link(sys.argv[1])
