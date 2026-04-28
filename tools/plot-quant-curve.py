#!/usr/bin/env python3
"""Plot z_avg vs bpw, colored by arch and imatrix, for models with ≥5 reliable sessions."""

import json, sqlite3
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from pathlib import Path

DB = Path.home() / ".claude/mem0/dataset.db"
REGISTRY = Path(__file__).parent.parent / "config/models-registry.json"

# --- pull scored models (same filter as the session queries) ---
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

rows = con.execute("""
WITH sess_stats AS (
  SELECT session_id,
         AVG(score_norm) AS sess_avg,
         SQRT(AVG(score_norm*score_norm) - AVG(score_norm)*AVG(score_norm)) AS sess_sd
  FROM score_normed_quality GROUP BY session_id
),
rezscored AS (
  SELECT s.model_norm, s.score_norm,
         (s.score_norm - st.sess_avg) / NULLIF(st.sess_sd, 0) AS z
  FROM score_normed_quality s JOIN sess_stats st USING (session_id)
)
SELECT model_norm,
       COUNT(*) AS n,
       AVG(z) AS z_avg,
       MIN(z) AS z_min,
       AVG(score_norm) AS avg_score
FROM rezscored
GROUP BY model_norm
HAVING COUNT(*) >= 5
""").fetchall()
con.close()

scored = {r["model_norm"]: dict(r) for r in rows}

# --- load registry and match ---
registry = json.loads(REGISTRY.read_text())

points = []
for key, entry in registry.items():
    norm = key.replace("/", "-").replace(".", "-").replace("_", "-").lower()
    # try exact match then fuzzy
    match = None
    for mn in scored:
        if norm in mn or mn in norm:
            match = mn
            break
    if not match:
        continue

    bpw = entry.get("bpw")
    if bpw is None:
        continue
    try:
        bpw = float(bpw)
    except (ValueError, TypeError):
        continue

    s = scored[match]
    arch = entry.get("arch", "?")
    has_imatrix = entry.get("hasImatrix", False)
    high_prec = entry.get("highPrecisionRatio")
    ultra_low = entry.get("ultraLowRatio")
    quant_strategy = entry.get("quantStrategy", "")
    file_gb = entry.get("fileSizeGb")
    model_type = entry.get("modelType", "?")
    perf = entry.get("performance", {})
    gen_tps = perf.get("tps", {}).get("avg")
    prefill_tps = perf.get("prefillTps")

    points.append({
        "key": key,
        "model_norm": match,
        "bpw": bpw,
        "z_avg": s["z_avg"],
        "z_min": s["z_min"],
        "avg_score": s["avg_score"],
        "arch": arch,
        "has_imatrix": has_imatrix,
        "high_prec": high_prec,
        "ultra_low": ultra_low,
        "quant_strategy": quant_strategy,
        "file_gb": file_gb,
        "model_type": model_type,
        "gen_tps": gen_tps,
        "prefill_tps": prefill_tps,
    })

print(f"Matched {len(points)} models with bpw data")
for p in sorted(points, key=lambda x: -x["z_avg"]):
    imat = "imat" if p["has_imatrix"] else "trad"
    print(f"  {p['key']:<50} bpw={p['bpw']:.2f}  z={p['z_avg']:+.3f}  arch={p['arch']:<6}  {imat}  hp={p['high_prec']}")

# --- plot ---
fig, axes = plt.subplots(1, 2, figsize=(14, 6))
fig.suptitle("Quant quality: bpw vs z_avg", fontsize=13, fontweight="bold")

# colour by arch, marker by imatrix
arch_colors = {"dense": "#2196F3", "moe": "#FF5722", "?": "#9E9E9E"}
marker_map = {True: "o", False: "s"}  # circle=imatrix, square=traditional

for ax_idx, ax in enumerate(axes):
    for p in points:
        color = arch_colors.get(p["arch"], "#9E9E9E")
        marker = marker_map[p["has_imatrix"]]
        ax.scatter(p["bpw"], p["z_avg"], c=color, marker=marker,
                   s=90, alpha=0.85, edgecolors="white", linewidths=0.6, zorder=3)
        # label on right plot only
        if ax_idx == 1:
            short = p["key"].split("/")[-1][:22]
            ax.annotate(short, (p["bpw"], p["z_avg"]),
                        textcoords="offset points", xytext=(6, 2),
                        fontsize=6.5, alpha=0.8)

    ax.axhline(0, color="#aaa", linewidth=0.8, linestyle="--", zorder=1)
    ax.set_xlabel("bits per weight (bpw)", fontsize=10)
    ax.set_ylabel("z_avg (quality vs session baseline)", fontsize=10)
    ax.set_title("Labelled" if ax_idx == 1 else "Clean", fontsize=10)
    ax.grid(True, alpha=0.25)

    # fit a trend line across all points
    xs = np.array([p["bpw"] for p in points])
    ys = np.array([p["z_avg"] for p in points])
    if len(xs) > 2:
        z = np.polyfit(xs, ys, 1)
        px = np.linspace(xs.min() - 0.2, xs.max() + 0.2, 100)
        ax.plot(px, np.polyval(z, px), color="#555", linewidth=1.2,
                linestyle=":", alpha=0.7, label=f"trend (slope={z[0]:+.3f})")
        ax.legend(fontsize=8)

# legend
legend_elements = [
    mpatches.Patch(color=arch_colors["dense"], label="dense"),
    mpatches.Patch(color=arch_colors["moe"],   label="MoE"),
    plt.Line2D([0], [0], marker="o", color="w", markerfacecolor="#555", markersize=8, label="imatrix"),
    plt.Line2D([0], [0], marker="s", color="w", markerfacecolor="#555", markersize=8, label="traditional"),
]
fig.legend(handles=legend_elements, loc="lower center", ncol=4, fontsize=9,
           bbox_to_anchor=(0.5, -0.02))

plt.tight_layout(rect=[0, 0.05, 1, 1])
out = Path(__file__).parent / "quant-curve.png"
plt.savefig(out, dpi=150, bbox_inches="tight")
print(f"\nSaved: {out}")

# --- imatrix vs traditional summary ---
imat = [p for p in points if p["has_imatrix"]]
trad = [p for p in points if not p["has_imatrix"]]
print(f"\nImatrix  n={len(imat)}  z_avg={np.mean([p['z_avg'] for p in imat]):+.3f}" if imat else "")
print(f"Trad     n={len(trad)}  z_avg={np.mean([p['z_avg'] for p in trad]):+.3f}" if trad else "")

# highPrecisionRatio vs z_avg
hp_pts = [(p["high_prec"], p["z_avg"]) for p in points if p["high_prec"] is not None]
if len(hp_pts) > 2:
    hx, hy = zip(*hp_pts)
    z = np.polyfit(hx, hy, 1)
    print(f"\nhighPrecisionRatio vs z_avg slope: {z[0]:+.3f}  (n={len(hp_pts)})")