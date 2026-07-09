"""
Plug-and-play demo: one Simulator, built from real Chicago Taxi + BDG2
data. Pick a scenario and a Scheduler to run it with -- that's the whole
demo. Add your own BaseScheduler subclass to SCHEDULERS below; nothing
else here needs to change.

Pick "all" to run every scheduler against the identical scenario -- each
gets its own triple-panel plot + fleet summary, plus one extra comparison
plot overlaying every scheduler's grid draw on the same building load
curve, so both the per-scheduler detail and the direct comparison are
available.

For a fast, dependency-free correctness check instead of exploration,
see tests/test_heuristic.py.
"""
from pathlib import Path

from simulator import Simulator
from scheduler.base import NullScheduler
from scheduler.heuristic import HeuristicScheduler
from scheduler.milp import MILPScheduler
from scenarios.small_scenario import build_scenario as build_small_scenario
from scenarios.chicago_scenario import build_scenario as build_chicago_scenario
from evaluation import metrics
from evaluation.plotting import plot_triple_panel, plot_comparison, summarize_fleet

# Both scenarios carry every field every scheduler needs (Null, Heuristic, or
# MILP), and both use real Chicago Taxi Trips data -- "small" isn't more
# real than "chicago", it's just a smaller/faster network (it additionally
# uses real BDG2 building data; chicago's building load is synthetic). The
# actual difference that matters when picking one is scale and MILP solve
# time -- see scenarios/chicago_scenario.py for what's tuned there and why.
SCENARIOS = {
    'small': (build_small_scenario, "5 vehicles, 3 nodes -- fast, seconds to solve"),
    'chicago': (build_chicago_scenario, "larger real Chicago-scale network -- see chicago_scenario.py for current size/solve-time notes"),
}

SCHEDULERS = {
    'null': lambda scenario, plan_path: NullScheduler(),
    'heuristic': lambda scenario, plan_path: HeuristicScheduler(),
    'milp': lambda scenario, plan_path: MILPScheduler(scenario, plan_path=plan_path),
}


def run(scenario, scheduler, label):
    sim = Simulator(scenario['network'], scenario['ride_demand'],
                     scenario['fleet'], scenario['buildings'], dt=scenario['dt'])

    building_ids = [b.b_id for b in sim.buildings.buildings]
    p_load_hist = {b: [] for b in building_ids}
    p_grid_hist = {b: [] for b in building_ids}
    p_v2b_hist = {b: [] for b in building_ids}
    p_cons_hist = {b: [] for b in building_ids}
    soc_hist = {v.v_id: [] for v in sim.fleet.vehicles}
    node_hist = {v.v_id: [] for v in sim.fleet.vehicles}
    arc_hist = {v.v_id: [] for v in sim.fleet.vehicles}
    p_hist = {v.v_id: [] for v in sim.fleet.vehicles}
    demand_flag_hist = {v.v_id: [] for v in sim.fleet.vehicles}
    served_ids = set()

    for _ in range(scenario['T']):
        state = sim.get_state()
        decisions = scheduler.decide(state)

        due_arcs = {(d['i_d'], d['j_d']): d['id'] for d in state['demands']}
        for v_state, dec in zip(state['fleet'], decisions['fleet']):
            v_id = v_state['v_id']
            # A vehicle already mid-transit keeps its existing arc; otherwise
            # a departure decision this timestep starts one. Node is only
            # meaningful when neither holds -- i.e. genuinely parked all of t.
            current_arc = v_state['arc'] if v_state['arc'] is not None else dec['arc']
            arc_hist[v_id].append(current_arc)
            node_hist[v_id].append(v_state['node'] if current_arc is None else None)
            is_demand = dec['arc'] in due_arcs
            demand_flag_hist[v_id].append(is_demand)
            if is_demand:
                served_ids.add(due_arcs[dec['arc']])

        sim.step(decisions)

        t = state['t']
        for b in sim.buildings.buildings:
            # Total electrical demand, not just the raw pre-HVAC load_profile
            # value -- for Mode B buildings (rc populated, e.g. chicago_scenario.py)
            # p_hvac can add up to hvac_max on top of load, and grid draw
            # (p_grid = total_load - p_cons) legitimately includes it. Recording
            # only the raw load here made grid draw appear to exceed "load" and
            # made peak_reduction() go negative (max(p_load) undercounted the
            # true peak) -- confirmed directly against chicago_scenario.py
            # (Building 2 hvac_max=80 produced peak_reduction=-80.00 kW).
            # p_hvac is always 0.0 for Mode A buildings (rc=None), so this is a
            # no-op there -- small_scenario.py's numbers are unaffected.
            p_load_hist[b.b_id].append(b.load_profile.get(t, 0.0) + b.p_hvac)
            p_grid_hist[b.b_id].append(b.p_grid)
            p_cons_hist[b.b_id].append(b.p_cons)
        for b_id, v in sim.p_v2b.items():
            p_v2b_hist[b_id].append(v)
        for v in sim.fleet.vehicles:
            soc_hist[v.v_id].append(v.soc)
            p_hist[v.v_id].append(v.p)

    all_demands = list(scenario['ride_demand'].demands)
    served = [d for d in all_demands if d['id'] in served_ids]
    rho = metrics.demand_fulfillment(served, all_demands, scenario['network']) if all_demands else 1.0

    print(f"\n--- {label} ---")
    for b_id in building_ids:
        dp = metrics.peak_reduction(p_load_hist[b_id], p_grid_hist[b_id])
        eta = metrics.v2b_utilization(p_v2b_hist[b_id], p_cons_hist[b_id])
        phi = metrics.temporal_alignment(p_v2b_hist[b_id], p_load_hist[b_id])
        print(f"  Building {b_id}: peak_reduction={dp:.2f} kW, "
              f"v2b_utilization={eta:.2%}, temporal_alignment={phi:.3f}")
    print(f"  Fleet: demand_fulfillment (rho) = {rho:.2%} ({len(served)}/{len(all_demands)})")

    return {
        'p_load_hist': p_load_hist, 'p_grid_hist': p_grid_hist,
        'soc_hist': soc_hist, 'node_hist': node_hist, 'arc_hist': arc_hist,
        'p_hist': p_hist, 'demand_flag_hist': demand_flag_hist,
    }


def _choose(options):
    """Reads a validated choice from stdin. Caller prints the question/options first."""
    while True:
        choice = input("> ").strip().lower()
        if choice in options:
            return choice
        print(f"'{choice}' isn't one of {list(options)}, try again.")


if __name__ == '__main__':
    print("Which scenario?")
    for key, (_, desc) in SCENARIOS.items():
        print(f"  {key}: {desc}")
    scenario_name = _choose(SCENARIOS)
    build_scenario = SCENARIOS[scenario_name][0]

    print("Which scheduler?")
    for key in list(SCHEDULERS) + ['all']:
        print(f"  {key}")
    name = _choose(list(SCHEDULERS) + ['all'])
    visualize = input("Save a plot? (y/n) > ").strip().lower().startswith('y')

    names = list(SCHEDULERS) if name == 'all' else [name]

    results = {}
    load_for_plot = None
    scenario_for_plot = None
    for n in names:
        scenario = build_scenario()  # fresh objects per run -- Simulator mutates fleet/buildings
        plan_path = f"data/milp_plan_{scenario_name}.pkl" if n == 'milp' else None
        if n == 'milp':
            print(f"Solving MILP (cached after first solve at {plan_path})...")
        scheduler = SCHEDULERS[n](scenario, plan_path)
        results[n] = run(scenario, scheduler, n)
        load_for_plot = results[n]['p_load_hist']
        scenario_for_plot = scenario

    if visualize:
        Path("outputs").mkdir(exist_ok=True)
        dt = scenario_for_plot['dt']
        building_nodes = set(scenario_for_plot['network'].building_nodes)

        # One triple panel + fleet summary per scheduler that actually ran --
        # "all" used to only produce the comparison overlay below, which shows
        # grid draw but not any scheduler's individual Gantt/SoC behavior.
        for n in names:
            r = results[n]
            path = f"outputs/run_{n}"
            plot_triple_panel(
                r['p_load_hist'], r['p_grid_hist'], r['node_hist'], r['arc_hist'],
                r['p_hist'], r['demand_flag_hist'], r['soc_hist'],
                building_nodes=building_nodes,
                save_path=path, dt=dt,
                s_min=scenario_for_plot['S_min'], s_max=scenario_for_plot['S_max'],
            )
            print(f"  Saved {n} plot to {path}.pdf / {path}.png")
            # The Gantt/SoC panels only draw the top-N most V2B-active
            # vehicles so the figure stays readable at any fleet size --
            # this fills in the rest as text, one line per vehicle.
            print(f"Fleet summary for {n} ({len(r['soc_hist'])} vehicles):")
            print(summarize_fleet(
                r['node_hist'], r['arc_hist'], r['p_hist'], r['demand_flag_hist'],
                r['soc_hist'], building_nodes, dt,
            ))
            print()

        if len(names) > 1:
            grid_hists = {n: results[n]['p_grid_hist'] for n in names}
            path = "outputs/run_comparison"
            plot_comparison(load_for_plot, grid_hists, "Scheduler comparison", path, dt=dt)
            print(f"Saved comparison plot to {path}.pdf / {path}.png")
