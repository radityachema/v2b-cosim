"""Visualization for a Simulator run's collected history."""
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

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

# color = building identity, linestyle = load vs. grid draw
_BUILDING_COLORS = ["#1a6faf", "#e67e22", "#27ae60", "#c0392b"]
_SOC_COLORS = plt.cm.tab10.colors

# Scheduler identity -> color (baseline/actual = gray, alternatives = orange/green/blue).
_SCHEDULER_COLORS = {
    "null": "#999999",
    "heuristic": "#e67e22",
    "milp": "#1a6faf",
}
_SCHEDULER_STYLES = {"null": ":", "heuristic": "--", "milp": "-."}

# Gantt-row state colors, one visual language for panel B across every run.
_GANTT_COLORS = {
    "building_discharge": "#c0392b",   # parked at a building, discharging (V2B)
    "building_charge":    "#1a6faf",   # parked at a building, charging
    "depot":              "#c9d6e3",   # idle at the depot
    "demand":             "#0b3d63",   # transit serving a ride demand
    "deadhead":           "#6baed6",   # transit with no passenger (repositioning)
}


def _vehicle_segments(node_hist, arc_hist, p_hist, demand_flag_hist, building_nodes):
    """Merges consecutive identical timesteps into one Gantt block, so labels stay readable."""
    T = len(node_hist)

    def key_at(t):
        if arc_hist[t] is not None:
            return ("transit", arc_hist[t])
        node = node_hist[t]
        if node in building_nodes:
            # sign is part of the merge key -- otherwise a vehicle oscillating charge/discharge
            # each timestep would collapse into one block with a misleading mean-power label
            return ("parked_building", node, p_hist[t] < 0)
        return ("parked", node)

    segs, seg_start, prev_key = [], 0, None
    for t in range(T):
        key = key_at(t)
        if key != prev_key:
            if prev_key is not None:
                segs.append((seg_start, t - 1, prev_key))
            prev_key, seg_start = key, t
    if prev_key is not None:
        segs.append((seg_start, T - 1, prev_key))

    # below this width labels just smear text -- color + legend already convey state,
    # summarize_fleet() has the exact numbers
    MIN_LABEL_WIDTH = 2

    results = []
    for ts, te, key in segs:
        width = te - ts + 1
        if key[0] == "parked_building":
            _, node, is_discharge = key
            p_mean = sum(p_hist[ts:te + 1]) / width
            lbl = f"{p_mean:+.1f}kW" if width >= MIN_LABEL_WIDTH and abs(p_mean) >= 0.3 else ""
            bkind = "building_discharge" if is_discharge else "building_charge"
            results.append((ts, te, bkind, lbl))
        elif key[0] == "parked":
            results.append((ts, te, "depot", ""))
        else:
            i, j = key[1]
            is_demand = any(demand_flag_hist[ts:te + 1])
            lbl = f"{i}→{j}" if width >= MIN_LABEL_WIDTH else ""
            if lbl and is_demand:
                lbl = f"[D] {lbl}"
            results.append((ts, te, "demand" if is_demand else "deadhead", lbl))
    return results


def _v2b_energy(node_hist, arc_hist, p_hist, building_nodes, dt):
    """Total |kWh| a vehicle exchanged while parked at a building (charge + discharge)."""
    return sum(
        abs(p_hist[t]) * dt
        for t in range(len(node_hist))
        if arc_hist[t] is None and node_hist[t] in building_nodes
    )


def summarize_fleet(node_hist, arc_hist, p_hist, demand_flag_hist, soc_hist,
                     building_nodes, dt):
    """One line per vehicle: trips served, V2B kWh, final SoC. Unlike the Gantt panel
    (top-N only), this covers every vehicle."""
    lines = []
    for v_id in sorted(soc_hist):
        segs = _vehicle_segments(node_hist[v_id], arc_hist[v_id], p_hist[v_id],
                                  demand_flag_hist[v_id], building_nodes)
        n_demand = sum(1 for _, _, kind, _ in segs if kind == "demand")
        dis = [dt * sum(p_hist[v_id][ts:te + 1])
               for ts, te, kind, _ in segs if kind == "building_discharge"]
        chg = [dt * sum(p_hist[v_id][ts:te + 1])
               for ts, te, kind, _ in segs if kind == "building_charge"]
        lines.append(
            f"V{v_id}: {n_demand} demand trip{'s' if n_demand != 1 else ''}, "
            f"V2B discharge {len(dis)}x ({sum(dis):+.1f} kWh total), "
            f"charge {len(chg)}x ({sum(chg):+.1f} kWh total), "
            f"final SoC {soc_hist[v_id][-1]:.2f}"
        )
    return "\n".join(lines)


def plot_triple_panel(p_load_hist, p_grid_hist, node_hist, arc_hist, p_hist,
                       demand_flag_hist, soc_hist, building_nodes,
                       save_path, dt, s_min, s_max, top_n=5):
    """Triple-panel run figure: (A) load vs. grid draw, (B) per-vehicle Gantt schedule,
    (C) SoC. Panels B/C show only the top_n vehicles by V2B energy exchanged;
    summarize_fleet() covers the rest."""
    building_ids = list(p_load_hist)
    all_vehicles = sorted(soc_hist)
    ranked = sorted(
        all_vehicles,
        key=lambda v: _v2b_energy(node_hist[v], arc_hist[v], p_hist[v], building_nodes, dt),
        reverse=True,
    )
    vehicles = sorted(ranked[:top_n])
    truncated = len(all_vehicles) > top_n
    T = len(p_load_hist[building_ids[0]])
    hours = [t * dt for t in range(T)]
    tick_x = list(range(0, 25, 4))
    tick_labels = [f"{h:02d}:00" for h in tick_x]

    # figure height scales with vehicle count so rotated labels have room
    n_v = max(len(vehicles), 1)
    fig, (ax_load, ax_gantt, ax_soc) = plt.subplots(
        3, 1, figsize=(7.0, 3.2 + 0.8 * n_v),
        gridspec_kw={"height_ratios": [1.6, 1.1 * n_v + 0.4, 1.6]})

    # Panel A -- building load vs. grid draw, same convention as plot_comparison.
    for i, b_id in enumerate(building_ids):
        color = _BUILDING_COLORS[i % len(_BUILDING_COLORS)]
        ax_load.plot(hours, p_load_hist[b_id], color=color, lw=1.6,
                     label=f"Building {b_id} load")
        ax_load.plot(hours, p_grid_hist[b_id], color=color, lw=1.4, ls="--",
                     label=f"Building {b_id} grid draw")
        ax_load.fill_between(hours, p_grid_hist[b_id], p_load_hist[b_id],
                              where=[g < l for g, l in zip(p_grid_hist[b_id], p_load_hist[b_id])],
                              color=color, alpha=0.15)
    ax_load.set_ylabel("kW")
    ax_load.set_xticks(tick_x)
    ax_load.set_xticklabels([])
    ax_load.set_xlim(0, max(hours))
    # anchored above axes -- an in-axes corner can collide with the load curve depending on scenario
    ax_load.set_title("A   Building load vs. grid draw", loc="left", fontsize=9, pad=22)
    ax_load.legend(loc="lower left", bbox_to_anchor=(0.0, 1.0), fontsize=7,
                    ncol=2, framealpha=0.9, borderaxespad=0.2)

    # Panel B -- Gantt.
    bar_h = 0.8
    for row, v_id in enumerate(vehicles):
        segs = _vehicle_segments(node_hist[v_id], arc_hist[v_id], p_hist[v_id],
                                  demand_flag_hist[v_id], building_nodes)
        for ts, te, kind, lbl in segs:
            x0 = ts * dt
            width = (te - ts + 1) * dt
            color = _GANTT_COLORS[kind]
            ax_gantt.barh(row, width, left=x0, height=bar_h, color=color,
                          align="center", edgecolor="white", linewidth=0.5)
            if lbl:
                text_color = "white" if kind in ("building_discharge", "building_charge", "demand") else "#222222"
                ax_gantt.text(x0 + width / 2, row, lbl, ha="center", va="center",
                              fontsize=6.5, color=text_color, fontweight="bold",
                              rotation=90 if width < 1.5 else 0, clip_on=True)
    ax_gantt.set_yticks(range(len(vehicles)))
    ax_gantt.set_yticklabels([f"V{v}" for v in vehicles])
    ax_gantt.set_ylim(-0.5, len(vehicles) - 0.5)
    ax_gantt.set_ylabel("Vehicle")
    ax_gantt.set_xticks(tick_x)
    ax_gantt.set_xticklabels([])
    ax_gantt.set_xlim(0, max(hours))
    # Title gets extra pad so it renders above the legend row instead of
    # underneath it -- both would otherwise sit right at the axes top edge.
    gantt_title = (f"B   Vehicle schedule (top {top_n} of {len(all_vehicles)} by V2B activity)"
                   if truncated else "B   Vehicle schedule")
    ax_gantt.set_title(gantt_title, loc="left", fontsize=9, pad=22)
    # anchored above axes, same reasoning as panel A's legend
    ax_gantt.legend(handles=[
        mpatches.Patch(color=_GANTT_COLORS["building_discharge"], label="Discharging (V2B)"),
        mpatches.Patch(color=_GANTT_COLORS["building_charge"], label="Charging"),
        mpatches.Patch(color=_GANTT_COLORS["depot"], label="Idle at depot"),
        mpatches.Patch(color=_GANTT_COLORS["demand"], label="[D] Passenger transit"),
        mpatches.Patch(color=_GANTT_COLORS["deadhead"], label="Deadhead transit"),
    ], fontsize=6.5, loc="lower left", bbox_to_anchor=(0.0, 1.0), ncol=5,
        framealpha=0.9, borderaxespad=0.2)

    # Panel C -- SoC. Color keyed to v_id, not position in `vehicles` -- so a
    # given vehicle keeps the same color across regenerations even if a
    # different top_n or a different ranking changes who else is shown.
    for v_id in vehicles:
        ax_soc.plot(hours, soc_hist[v_id], color=_SOC_COLORS[v_id % len(_SOC_COLORS)],
                    lw=1.2, label=f"V{v_id}")
    ax_soc.axhline(s_min, color="gray", lw=0.8, ls="--", label=f"s_min={s_min}")
    ax_soc.axhline(s_max, color="gray", lw=0.8, ls=":", label=f"s_max={s_max}")
    ax_soc.set_ylim(-0.02, 1.02)
    ax_soc.set_ylabel("SoC")
    ax_soc.set_xlabel("Time of day (h)")
    ax_soc.set_xticks(tick_x)
    ax_soc.set_xticklabels(tick_labels)
    ax_soc.set_xlim(0, max(hours))
    soc_title = f"C   Vehicle SoC (top {top_n} of {len(all_vehicles)})" if truncated else "C   Vehicle SoC"
    ax_soc.set_title(soc_title, loc="left", fontsize=9)
    if len(vehicles) <= 12:
        ax_soc.legend(loc="upper right", fontsize=7, ncol=2)

    fig.tight_layout()
    fig.savefig(f"{save_path}.pdf", bbox_inches="tight")
    fig.savefig(f"{save_path}.png", bbox_inches="tight")
    plt.close(fig)


def plot_comparison(p_load_hist, grid_hists_by_scheduler, title, save_path, dt=1.0):
    """One grid-draw line per scheduler overlaid on building load, one subplot per building."""
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
