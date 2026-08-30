# Demo ao vivo — Dashboard + MOGA Engine (apresentação para o comitê)

## Preparação (antes da apresentação)

1. Nesta pasta devem estar: `interactive_dashboard.html`, `moga_flood_preservation.py` e `moga_server.py`.
2. Confirme que o Python 3 tem matplotlib: `pip install matplotlib`
3. Teste uma vez antes do dia D (passos abaixo).

## No dia da apresentação

1. Abra um terminal nesta pasta e rode: `python moga_server.py`
2. Abra no navegador: **http://localhost:8000/interactive_dashboard.html**
   (importante: pela URL do servidor, não abrindo o arquivo direto)
3. No card **3D Pareto Front — MOGA Multi-Seed**, clique **▶ RUN MOGA ENGINE**.

## O que mostrar

- O run ao vivo usa os valores atuais dos sliders de **Building Profile** (flood depth, shear cap., wall length, basement H) — mude um slider, rode de novo e o vencedor muda.
- Configuração rápida recomendada ao vivo: **5 seeds × 60 gerações (~20 s)**. O terminal mostra o progresso geração a geração (bom para projetar junto).
- O status verde mostra: tempo do run, nº de pontos Pareto e o vencedor (estratégia, PH, VIF, objetivos).
- Sem o servidor rodando, o dashboard continua funcionando normalmente com o run completo embutido (20 seeds × 300 gens, 2026-08-19) — mensagem vermelha avisa que o engine está offline.

## Tempos aproximados (medidos)

| Configuração | Tempo |
|---|---|
| 5 seeds × 60 gens | ~20 s |
| 10 seeds × 60 gens | ~40 s |
| 20 seeds × 300 gens (full) | ~5 min |

## Outros arquivos nesta pasta

- `moga_pareto_data.json` — resultados do run completo (999 pontos Pareto, também já embutidos no HTML)
- `run_and_export.py` — wrapper que roda o run completo e exporta o JSON + PNGs
- `consultant_report_latest.txt` / `run_output_v3.txt` — relatório e log do run completo
- `visualizations/` — todos os PNGs gerados pelo engine
