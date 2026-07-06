"""
Visualization for a Simulator run's collected history. Publication-style
formatting -- serif font, muted color palette, time-of-day x-axis,
print-resolution PDF + PNG output -- so figures are ready to drop into a
paper without reformatting. Always saves to file (not plt.show()) --
robust regardless of whether a display is available, and gives you a
file to compare across runs.
"""
import matplotlib.pyplot as plt

plt.rcParams.update({
    "font.family":     "serif",
    "font.size":       10,
    "axes.labelsize":  10,
    "axes.titlesize":  10,
    "legend.fontsize": 9,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "figure.dpi":      150,
    "savefig.dpi":     300,
    "axes.grid":       True,
    "grid.alpha":      0.25,
    "grid.linestyle":  "--",
})

# One color per building identity, cycled if there are more than 4.
# Load = solid, grid draw = dashed of the same color -- same convention
# as plot_results.py (linestyle distinguishes a variant, color distinguishes
# identity).
_BUILDING_COLORS = ["#1a6faf", "#e67e22", "#27ae60", "#c0392b"]
_SOC_COLORS = plt.cm.tab10.colors

# Scheduler identity -> color, matching plot_results.py's convention
# (baseline/actual = gray, alternatives = orange/green/blue).
_SCHEDULER_COLORS = {
    "null": "#999999",
    "heuristic": "#e67e22",
    "milp": "#1a6faf",
}
_SCHEDULER_STYLES = {"null": ":", "heuristic": "--", "milp": "-."}


def plot_run(p_load_hist, p_grid_hist, soc_hist, title, save_path, dt=1.0):
    """
    p_load_hist, p_grid_hist : dict {b_id: [kW per timestep]}
    soc_hist                 : dict {v_id: [SoC per timestep]}
    save_path                : path without extension -- saves .pdf and .png
    dt                       : hours per timestep, for the time-of-day x-axis
    """
    T = len(next(iter(p_load_hist.values())))
    hours = [t * dt for t in range(T)]
    tick_x = list(range(0, 25, 4))
    tick_labels = [f"{h:02d}:00" for h in tick_x]

    fig, (ax_load, ax_soc) = plt.subplots(2, 1, figsize=(6.5, 6.0))
    fig.suptitle(title)

    for i, b_id in enumerate(p_load_hist):
        color = _BUILDING_COLORS[i % len(_BUILDING_COLORS)]
        ax_load.plot(hours, p_load_hist[b_id], color=color, lw=1.8,
                     label=f"Building {b_id} load")
        ax_load.plot(hours, p_grid_hist[b_id], color=color, lw=1.6, ls="--",
                     label=f"Building {b_id} grid draw")
    ax_load.set_xlabel("Time of day (h)")
    ax_load.set_ylabel("kW")
    ax_load.set_xticks(tick_x)
    ax_load.set_xticklabels(tick_labels)
    ax_load.set_xlim(0, max(hours))
    ax_load.set_title("Building load vs. grid draw")
    ax_load.legend(loc="upper left", fontsize=8)

    for i, (v_id, soc) in enumerate(soc_hist.items()):
        ax_soc.plot(hours, soc, color=_SOC_COLORS[i % len(_SOC_COLORS)], lw=1.2,
                    label=f"V{v_id}")
    ax_soc.set_xlabel("Time of day (h)")
    ax_soc.set_ylabel("SoC")
    ax_soc.set_xticks(tick_x)
    ax_soc.set_xticklabels(tick_labels)
    ax_soc.set_xlim(0, max(hours))
    ax_soc.set_title("Vehicle SoC")
    if len(soc_hist) <= 12:
        ax_soc.legend(loc="upper left", fontsize=7, ncol=2)

    fig.tight_layout()
    fig.savefig(f"{save_path}.pdf", bbox_inches="tight")
    fig.savefig(f"{save_path}.png", bbox_inches="tight")
    plt.close(fig)


def plot_comparison(p_load_hist, grid_hists_by_scheduler, title, save_path, dt=1.0):
    """
    The actual comparison figure: one building load curve, one grid-draw
    line per scheduler overlaid on it -- same scenario, same building,
    different decision-maker. One subplot per building.

    p_load_hist              : dict {b_id: [kW per timestep]}
    grid_hists_by_scheduler  : dict {scheduler_name: {b_id: [kW per timestep]}}
    save_path                : path without extension -- saves .pdf and .png
    """
    building_ids = list(p_load_hist)
    T = len(next(iter(p_load_hist.values())))
    hours = [t * dt for t in range(T)]
    tick_x = list(range(0, 25, 4))
    tick_labels = [f"{h:02d}:00" for h in tick_x]

    fig, axes = plt.subplots(len(building_ids), 1, figsize=(6.5, 3.2 * len(building_ids)))
    if len(building_ids) == 1:
        axes = [axes]
    fig.suptitle(title)

    for ax, b_id in zip(axes, building_ids):
        ax.plot(hours, p_load_hist[b_id], color="#222222", lw=1.8, label="Building load")
        for name, grid_hists in grid_hists_by_scheduler.items():
            color = _SCHEDULER_COLORS.get(name, "#555555")
            style = _SCHEDULER_STYLES.get(name, "--")
            ax.plot(hours, grid_hists[b_id], color=color, lw=1.6, ls=style,
                     label=f"{name} grid draw")
        ax.set_xlabel("Time of day (h)")
        ax.set_ylabel("kW")
        ax.set_xticks(tick_x)
        ax.set_xticklabels(tick_labels)
        ax.set_xlim(0, max(hours))
        ax.set_title(f"Building {b_id}")
        ax.legend(loc="upper left", fontsize=8)

    fig.tight_layout()
    fig.savefig(f"{save_path}.pdf", bbox_inches="tight")
    fig.savefig(f"{save_path}.png", bbox_inches="tight")
    plt.close(fig)
