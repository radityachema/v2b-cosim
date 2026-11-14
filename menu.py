"""Terminal main menu on top of runner.py:  python menu.py

    New run / Settings / Past runs / Quit

Settings are kept for the session (scenario, nodes, buildings, vehicles, scheduler).
Every run writes to its own folder  outputs/<date>_<time>_<scheduler>_<scenario>/
holding settings.yaml, summary.txt and the plots. runner.py is reused as-is
(its run() does the simulation and printing); nothing here changes the physics."""
import contextlib
import io
import sys
import time
from datetime import datetime
from functools import partial
from pathlib import Path

import runner
from scenarios.scaled_scenario import n_buildings_for, default_vehicles
from scenarios.toy_scenario import build_scenario as build_toy_scenario
from evaluation.plotting import plot_triple_panel, plot_comparison, summarize_fleet

OUT_ROOT = Path("outputs")
SCENARIO_NAMES = ['toy', 'small', 'chicago', 'scaled']
SCHEDULER_NAMES = ['null', 'heuristic', 'milp']
TOY_BOUNDS = {'S_min': 0.1, 'S_max': 0.9}  # toy_scenario's vehicles are built with these
MILP_OK = {'small', 'scaled'}  # the MILP needs the scenario's *_milp keys; toy has none, chicago does not solve

DEFAULTS = {'scenario': 'small', 'nodes': 11, 'buildings': None, 'vehicles': None, 'scheduler': 'heuristic'}


def describe(s):
    """One-line summary of the current settings (None = scenario default)."""
    if s['scenario'] != 'scaled':
        return f"scenario={s['scenario']}  scheduler={s['scheduler']}"
    nb = s['buildings'] if s['buildings'] is not None else n_buildings_for(s['nodes'])
    v = s['vehicles'] if s['vehicles'] is not None else default_vehicles(s['nodes'])
    return (f"scenario=scaled  nodes={s['nodes']}  buildings={nb}  vehicles={v}  "
            f"scheduler={s['scheduler']}")


def run_name(s, stamp):
    sc = s['scenario']
    if sc == 'scaled':
        nb = s['buildings'] if s['buildings'] is not None else n_buildings_for(s['nodes'])
        sc = f"scaled_N{s['nodes']}_B{nb}"
    return f"{stamp}_{s['scheduler']}_{sc}"


def write_settings_yaml(path, s, extra):
    lines = [f"{k}: {'null' if v is None else v}" for k, v in {**s, **extra}.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def builder_for(s):
    """(build_scenario callable, cache key for MILP plans)."""
    sc = s['scenario']
    if sc == 'toy':
        return build_toy_scenario, 'toy'
    if sc == 'scaled':
        kwargs = {'n_nodes': s['nodes'], 'n_vehicles': s['vehicles'], 'n_buildings': s['buildings']}
        key = f"scaled_N{s['nodes']}_B{s['buildings']}_V{s['vehicles']}"
        return partial(runner.SCENARIOS['scaled'][0], **kwargs), key
    return runner.SCENARIOS[sc][0], sc


def new_run(s):
    if s['scheduler'] == 'milp' and s['scenario'] not in MILP_OK:
        print(f"The MILP scheduler is not available for '{s['scenario']}' "
              f"(toy has no MILP data; chicago does not solve). Change the scheduler in Settings.")
        return
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    out_dir = OUT_ROOT / run_name(s, stamp)
    k = 2
    while out_dir.exists():  # two runs in the same minute: never overwrite
        out_dir = OUT_ROOT / f"{run_name(s, stamp)}_{k}"
        k += 1
    out_dir.mkdir(parents=True)
    build, key = builder_for(s)
    plan_path = f"data/milp_plan_{key}.pkl" if s['scheduler'] == 'milp' else None

    print(f"\nRunning: {describe(s)}\nOutput folder: {out_dir}")
    t0 = time.time()
    scenario = build()  # fresh objects per run -- Simulator mutates fleet/buildings
    if plan_path:
        print(f"Solving MILP (cached after first solve at {plan_path})...")
    scheduler = runner.SCHEDULERS[s['scheduler']](scenario, plan_path)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):  # run() prints metrics; we keep them and echo them below
        res = runner.run(scenario, scheduler, s['scheduler'])
    summary = buf.getvalue()
    print(summary)
    elapsed = time.time() - t0

    nodes = scenario['network'].nodes
    building_nodes = set(scenario['network'].building_nodes)
    path = str(out_dir / f"run_{s['scheduler']}")
    plot_triple_panel(
        res['p_load_hist'], res['p_grid_hist'], res['node_hist'], res['arc_hist'],
        res['p_hist'], res['demand_flag_hist'], res['soc_hist'],
        building_nodes=building_nodes, save_path=path, dt=scenario['dt'],
        s_min=scenario.get('S_min', TOY_BOUNDS['S_min']),
        s_max=scenario.get('S_max', TOY_BOUNDS['S_max']),
    )
    fleet_txt = summarize_fleet(res['node_hist'], res['arc_hist'], res['p_hist'],
                                res['demand_flag_hist'], res['soc_hist'], building_nodes, scenario['dt'])
    (out_dir / "summary.txt").write_text(summary + "\n" + str(fleet_txt) + "\n", encoding="utf-8")
    write_settings_yaml(out_dir / "settings.yaml", s, {
        'n_nodes_actual': len(nodes), 'n_buildings_actual': len(building_nodes),
        'n_vehicles_actual': len(scenario['fleet'].vehicles), 'run_seconds': round(elapsed, 1)})
    print(f"Done in {elapsed:.1f}s. Saved plot, summary.txt and settings.yaml to {out_dir}/")


def ask_int(prompt, lo, hi=None, allow_default=False):
    while True:
        raw = input(prompt).strip().lower()
        if allow_default and raw in ('', 'default', 'd'):
            return None
        if raw.lstrip('-').isdigit() and int(raw) >= lo and (hi is None or int(raw) <= hi):
            return int(raw)
        print(f"  enter a whole number >= {lo}" + (f" and <= {hi}" if hi else "")
              + (", or press Enter for the default" if allow_default else ""))


def ask_choice(prompt, options):
    print(prompt)
    for i, o in enumerate(options, 1):
        print(f"  {i}) {o}")
    while True:
        raw = input("> ").strip().lower()
        if raw in options:
            return raw
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        print("  pick a number or a name from the list")


def settings_menu(s):
    while True:
        print(f"\n--- Settings ---\n  {describe(s)}")
        items = ['scenario', 'scheduler']
        if s['scenario'] == 'scaled':
            items += ['nodes', 'buildings', 'vehicles']
        items.append('back')
        choice = ask_choice("Change which setting?", items)
        if choice == 'back':
            return
        if choice == 'scenario':
            s['scenario'] = ask_choice("Scenario:", SCENARIO_NAMES)
            if s['scenario'] != 'scaled':
                s['buildings'] = s['vehicles'] = None
        elif choice == 'scheduler':
            s['scheduler'] = ask_choice("Scheduler:", SCHEDULER_NAMES)
        elif choice == 'nodes':
            s['nodes'] = ask_int("Number of nodes N (>= 2) > ", 2)
            if s['buildings'] is not None and s['buildings'] > s['nodes'] - 1:
                print(f"  buildings reset to default (must be <= N-1 = {s['nodes'] - 1})")
                s['buildings'] = None
        elif choice == 'buildings':
            s['buildings'] = ask_int(f"Number of buildings (1..{s['nodes'] - 1}, Enter = "
                                     f"default {n_buildings_for(s['nodes'])}) > ",
                                     1, s['nodes'] - 1, allow_default=True)
        elif choice == 'vehicles':
            s['vehicles'] = ask_int(f"Number of vehicles (>= 1, Enter = default "
                                    f"{default_vehicles(s['nodes'])}) > ", 1, allow_default=True)


def past_runs():
    runs = sorted((p for p in OUT_ROOT.glob("*") if p.is_dir()), reverse=True) if OUT_ROOT.exists() else []
    if not runs:
        print("\nNo past runs yet (outputs/ has no run folders).")
        return
    print("\n--- Past runs (newest first) ---")
    for i, p in enumerate(runs, 1):
        print(f"  {i}) {p.name}")
    raw = input("Number to show its settings and summary, Enter to go back > ").strip()
    if raw.isdigit() and 1 <= int(raw) <= len(runs):
        for f in ('settings.yaml', 'summary.txt'):
            fp = runs[int(raw) - 1] / f
            if fp.exists():
                print(f"\n[{f}]\n{fp.read_text(encoding='utf-8')}")


def main():
    s = dict(DEFAULTS)
    while True:
        print(f"\n=== v2b-cosim ===\nCurrent: {describe(s)}")
        choice = ask_choice("Main menu:", ['new run', 'settings', 'past runs', 'quit'])
        if choice == 'new run':
            new_run(s)
        elif choice == 'settings':
            settings_menu(s)
        elif choice == 'past runs':
            past_runs()
        else:
            print("Bye.")
            return


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nBye.")
        sys.exit(0)
