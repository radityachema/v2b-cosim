"""
Visualization for a Simulator run's collected history. Publication-style
formatting -- serif font, muted color palette, time-of-day x-axis,
print-resolution PDF + PNG output -- so figures are ready to drop into a
paper without reformatting. Always saves to file (not plt.show()) --
robust regardless of whether a display is available, and gives you a
file to compare across runs.
"""
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

# One color per building identity, cycled if there are more than 4.
# Load = solid, grid draw = dashed of the same color -- linestyle
# distinguishes a variant, color distinguishes identity.
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
    """
    Collapse one vehicle's per-timestep (node, arc) history into merged
    (t_start, t_end, kind, label) blocks for the Gantt panel. `kind` is one
    of _GANTT_COLORS's keys. A block spanning multiple identical timesteps
    (e.g. several parked timesteps in a row) becomes one bar, not one per
    timestep, so labels stay readable.
    """
    T = len(node_hist)

    def key_at(t):
        if arc_hist[t] is not None:
            return ("transit", arc_hist[t])
        node = node_hist[t]
        if node in building_nodes:
            # Charge/discharge sign is part of the merge key, not just the
            # node -- a vehicle sawtoothing at its SoC floor for hours
            # (confirmed: chicago_scenario.py's heuristic run gets vehicles
            # stuck alternating +-10kW every timestep once parked, since the
            # heuristic never routes an idle vehicle away from a building
            # with nothing else to do) would otherwise merge into ONE block
            # labeled with the mean power -- which can look like a small,
            # calm number while hiding a real 20kW swing every timestep.
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

    # Labels only add value when a block is wide enough to read -- at hourly
    # resolution with tau=1 arcs, most transit blocks are a single timestep,
    # and a vehicle oscillating at a building now produces many 1-timestep
    # building blocks too (see key_at above). Labeling every one of them
    # just smears text across the whole row; color alone (+ the legend)
    # already conveys what's happening, and summarize_fleet() has the exact
    # numbers for any vehicle a reader wants to check.
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
    """
    One line per vehicle -- demand trips served, V2B discharge/charge blocks and
    their total kWh, final SoC. Covers every vehicle, unlike the Gantt panel
    (which only draws the top-N by V2B activity so it stays readable at any
    fleet size) -- this is the complete record it's a summary of.
    """
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
    """
    Triple-panel run figure: (A) building load vs. grid draw, (B) per-vehicle
    schedule as a Gantt chart (parked-at-building / idle-at-depot / passenger
    transit / deadhead transit), (C) vehicle SoC. Replaces the older
    load+SoC-only plot_run -- adding the Gantt row is what actually shows a
    V2B interaction happening (a vehicle parked at a building, discharging),
    not just its downstream effect on the load curve.

    Panels B and C draw only the top_n vehicles by total V2B energy exchanged
    (charge + discharge kWh at a building) -- a fixed row-per-vehicle Gantt
    doesn't scale to a 30-vehicle fleet, and the vehicles that never touch a
    building aren't what this figure is showing. Every vehicle still shows up
    in the fleet-wide text summary_fleet() produces -- nothing is lost, it's
    just not all crammed into one figure. If the fleet has top_n or fewer
    vehicles, all of them are shown (small_scenario.py's 5-vehicle fleet is
    unaffected by this change).

    p_load_hist, p_grid_hist                     : dict {b_id: [kW per t]}
    node_hist, arc_hist, p_hist, demand_flag_hist : dict {v_id: [.. per t]},
        as recorded by runner.py's run() -- node/arc describe where the
        vehicle is during each timestep, p is the charge/discharge rate
        actually applied, demand_flag marks a timestep whose departure
        decision served a ride demand.
    soc_hist                                      : dict {v_id: [SoC per t]}
    """
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

    # Panel B needs real vertical room per row -- a rotated label ("i->j" or
    # a kW figure on a narrow block) is drawn top-to-bottom, so a cramped row
    # clips it regardless of font size. Scale both total figure height and
    # panel B's share of it with vehicle count, rather than a fixed split.
    # No fig-level suptitle -- that space goes to the Gantt panel instead;
    # `title` is dropped rather than relocated onto an axes title, so it
    # doesn't eat into the same space it was just freed from.
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
    # Legend anchored above the axes, same fix as panel B's -- an in-axes
    # corner ("upper left") collides with real data whenever the load curve
    # rises early or spans most of the y-range, which chicago_scenario.py's
    # larger synthetic load does. Title gets matching pad so it renders
    # above the legend instead of underneath it.
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
    # Anchored above the axes (not "upper right" inside it) so it never sits
    # on top of a busy row -- row occupancy varies by scenario/vehicle count,
    # an in-axes corner can't be picked once and trusted to stay clear.
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
