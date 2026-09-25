#!/usr/bin/env python3
"""
ETR Master's Thesis - Publication Figure Generator
Reads: thesis_results/thesis_summary_table.csv
Outputs in thesis_figures/:
  - Figure 4.1: Verdict Breakdown (Stacked Bar)
  - Figure 4.2: Median CPM Degradation (Bar Chart)
  - Figure 4.3: Pareto Trade-off Frontier: Privacy vs. Usability (Scatter)
  - Figure 4.4: Re-Identification Rate Comparison (Bar Chart)
"""

import matplotlib
matplotlib.use("Agg")  
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from pathlib import Path

INPUT_FILE = Path("thesis_summary_table.csv")
OUTPUT_DIR = Path("thesis_figures")
OUTPUT_DIR.mkdir(exist_ok=True)

if not INPUT_FILE.exists():
    raise FileNotFoundError(f"Could not find {INPUT_FILE}. Run evaluate_all_workers.py first.")

# --- Matplotlib Academic Styling ---
plt.rcParams.update({
    "font.family": "serif",
    "font.size": 11,
    "axes.labelsize": 12,
    "axes.titlesize": 13,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "figure.dpi": 300,
    "axes.grid": True,
    "grid.alpha": 0.35,
    "grid.linestyle": "--"
})

# --- Load & Clean Data ---
df = pd.read_csv(INPUT_FILE)

# Clean percentage strings to floats
def parse_pct(val):
    if isinstance(val, str):
        return float(val.replace("%", "").strip())
    return float(val)

high_res = df["High Resistance (%)"].apply(parse_pct).values
low_res = df["Low/Tracked (%)"].apply(parse_pct).values
partial_res = np.maximum(0.0, 100.0 - high_res - low_res)
cpm_delta = df["Median CPM Delta (%)"].apply(parse_pct).values
u_cost = df["U_cost (Breakage)"].astype(float).values
r_id = df["R_ID (Re-ID Rate)"].astype(float).values * 100.0
etr_score = df["ETR Metric Score"].astype(float).values

# Human-readable labels
labels = [
    "Chrome\nBaseline",
    "Firefox\nBaseline",
    "Firefox\nRFP",
    "Brave\nBaseline",
    "Brave\nStrict"
]
x = np.arange(len(labels))

print("[*] Generating academic figures...")

# =====================================================================
# FIGURE 4.1: Stacked Bar Chart of Tracking Resistance Verdicts
# =====================================================================
fig, ax = plt.subplots(figsize=(8, 4.5))
bar_width = 0.52

p1 = ax.bar(x, high_res, width=bar_width, label="High Resistance (Δ ≤ -30%)", 
            color="#2ca02c", edgecolor="black", linewidth=0.8)
p2 = ax.bar(x, partial_res, width=bar_width, bottom=high_res, label="Partial Resistance", 
            color="#ff7f0e", edgecolor="black", linewidth=0.8)
p3 = ax.bar(x, low_res, width=bar_width, bottom=high_res + partial_res, 
            label="Low Resistance (Tracking Persisted)", color="#d62728", edgecolor="black", linewidth=0.8)

# Add percentages inside the High Resistance segments
for idx, rect in enumerate(p1):
    h = rect.get_height()
    if h > 5:
        ax.text(rect.get_x() + rect.get_width() / 2., h / 2., f"{h:.1f}%",
                ha="center", va="center", color="white", fontweight="bold", fontsize=10)

ax.set_ylabel("Proportion of Active Auctions (%)")
ax.set_title("Causal Tracking Resistance Outcomes Across Browsers", pad=12)
ax.set_xticks(x)
ax.set_xticklabels(labels)
ax.set_ylim(0, 100)
ax.legend(loc="upper right", frameon=True, framealpha=0.95)

plt.tight_layout()
plt.savefig(OUTPUT_DIR / "fig1_verdicts_stacked.pdf")
plt.savefig(OUTPUT_DIR / "fig1_verdicts_stacked.png")
plt.close()
print("  [+] Saved Figure 1 (Verdicts Stacked Bar)")

# =====================================================================
# FIGURE 4.2: Median CPM Delta (% Economic Deprivation)
# =====================================================================
fig, ax = plt.subplots(figsize=(8.5, 5.2))
colors = ["#d62728" if v >= -5 else ("#1f77b4" if v >= -30 else "#2ca02c") for v in cpm_delta]
bars = ax.bar(x, cpm_delta, width=0.5, color=colors, edgecolor="black", linewidth=0.8)

ax.axhline(0, color="black", linewidth=1.0)
ax.axhline(-10, color="orange", linestyle=":", linewidth=1.0, alpha=0.7, label="Partial Threshold (-10%)")
ax.axhline(-30, color="green", linestyle="--", linewidth=1.0, alpha=0.7, label="High Resistance Threshold (-30%)")

ax.set_ylabel("Median CPM Bid Delta (%)")
ax.set_title("Economic Disruption Inflicted on RTB Bids\n(Phase 3 vs. Phase 1B)", pad=14)
ax.set_xticks(x)
ax.set_xticklabels(labels)
ax.set_ylim(-75, 10)
ax.legend(loc="lower left", frameon=True, framealpha=0.95, fontsize=9)

for bar, val in zip(bars, cpm_delta):
    h = bar.get_height()
    y_pos = h - 4.5 if h < 0 else h + 1.2
    ax.text(bar.get_x() + bar.get_width() / 2.0, y_pos, f"{val:.1f}%", 
            ha="center", va="center", fontweight="bold", fontsize=10)

plt.tight_layout()
plt.savefig(OUTPUT_DIR / "fig2_cpm_delta.pdf", bbox_inches="tight")
plt.savefig(OUTPUT_DIR / "fig2_cpm_delta.png", bbox_inches="tight")
plt.close()
print("  [+] Saved Figure 2 (Median CPM Delta)")

# =====================================================================
# FIGURE 4.3: Pareto Frontier (Privacy vs. Usability Trade-off)
# =====================================================================
fig, ax = plt.subplots(figsize=(8.2, 5.2))
point_colors = ["#d62728", "#7f7f7f", "#1f77b4", "#17becf", "#2ca02c"]

for i, txt in enumerate(["Chrome Base", "FF Base", "FF Hardened (RFP)", "Brave Base", "Brave Strict"]):
    ax.scatter(u_cost[i], high_res[i], s=220, color=point_colors[i], 
               edgecolors="black", linewidth=1.5, zorder=5)
    
    xy_offsets = {
        0: (12, -4),
        1: (12, -8),
        2: (12, 6),
        3: (12, -4),
        4: (-85, -12)
    }
    ax.annotate(f"{txt}", (u_cost[i], high_res[i]), 
                textcoords="offset points", xytext=xy_offsets[i], 
                fontweight="bold", fontsize=10)

# Connect the Pareto-optimal frontier points (FF RFP -> Brave Strict)
ax.plot([u_cost[2], u_cost[4]], [high_res[2], high_res[4]], 
        color="purple", linestyle="--", linewidth=1.8, label="Pareto Frontier", zorder=3)

# Two-line labels with padding so nothing gets clipped
ax.set_xlabel("Site Breakage Index ($U_{cost}$) — Lower is Better\n(0.0 = Baseline Compatibility)", 
              labelpad=10)
ax.set_ylabel("High Tracking Resistance Auctions (%)\n[Higher is Better]", 
              labelpad=12)

ax.set_title("Empirical Pareto Frontier (Privacy vs. Compatibility)", pad=14)
ax.set_xlim(-0.06, 0.55)
ax.set_ylim(22, 55)
ax.axvspan(-0.06, 0.05, color="green", alpha=0.08, label="Zero Incremental Breakage Zone")
ax.legend(loc="lower right", frameon=True, framealpha=0.95, fontsize=9.5)

plt.tight_layout()
# bbox_inches="tight" dynamically recalculates canvas borders
plt.savefig(OUTPUT_DIR / "fig3_pareto_frontier.pdf", bbox_inches="tight")
plt.savefig(OUTPUT_DIR / "fig3_pareto_frontier.png", bbox_inches="tight")
plt.close()
print("  [+] Saved Figure 3 (Pareto Frontier)")

# =====================================================================
# FIGURE 4.4: Re-Identification Rate (R_ID) Comparison
# =====================================================================
fig, ax = plt.subplots(figsize=(7.2, 4.2))
bars = ax.bar(x, r_id, width=0.48, color="#4863A0", edgecolor="black", linewidth=0.8)

ax.axhline(50, color="gray", linestyle=":", linewidth=1.0, alpha=0.7, label="Coin-flip Baseline (50%)")
ax.set_ylabel("Re-Identification Rate ($R_{ID}$) (%)")
ax.set_title("Advertiser Persona Persistence Rate Across Identity Break", pad=12)
ax.set_xticks(x)
ax.set_xticklabels(labels)
ax.set_ylim(0, 80)
ax.legend(loc="lower right", frameon=True, framealpha=0.95)

for bar in bars:
    h = bar.get_height()
    ax.text(bar.get_x() + bar.get_width() / 2.0, h + 2.0, f"{h:.1f}%", 
            ha="center", va="bottom", fontweight="bold", fontsize=10)

plt.tight_layout()
plt.savefig(OUTPUT_DIR / "fig4_reid_rate.pdf")
plt.savefig(OUTPUT_DIR / "fig4_reid_rate.png")
plt.close()
print("  [+] Saved Figure 4 (Re-ID Rates)")

print("\n[!] All 4 figures generated in 'thesis_figures/':")
for ext in ["pdf", "png"]:
    for f in ["fig1_verdicts_stacked", "fig2_cpm_delta", "fig3_pareto_frontier", "fig4_reid_rate"]:
        print(f"    - thesis_figures/{f}.{ext}")