"""
Task 3 -- comparability check. Runs HeuristicScheduler and MILPScheduler on
IDENTICAL scenario data (same network, same 30 vehicles with identical
parameters, same 317 real demands, same building load/RC config) and
reports (peak reduction, demand fulfillment) for both side by side.

Two known, expected asymmetries -- not bugs, stated here rather than left
implicit:
  - The MILP has hard terminal constraints (return to depot, end-of-day
    SoC >= S_init) from full-day foresight. The heuristic has no
    equivalent -- it's genuinely reactive.
  - The MILP enforces a hard demand-service floor (lambda=1.0 here). The
    heuristic has no service target at all, it serves whatever it's
    opportunistically positioned for.
Both reasons peak reduction alone would be a misleading comparison --
report both metrics, not one.
"""
from simulator import Simulator
from scheduler.heuristic import HeuristicScheduler
from scheduler.milp import MILPScheduler
from scenarios.chicago_scenario import build_scenario
from evaluation import metrics


def run_scheduler(scenario, scheduler, label):
    sim = Simulator(scenario['network'], scenario['ride_demand'],
                     scenario['fleet'], scenario['buildings'], dt=scenario['dt'])

    building_ids = scenario['building_nodes']
    p_load_hist = {b: [] for b in building_ids}
    p_grid_hist = {b: [] for b in building_ids}
    p_v2b_hist = {b: [] for b in building_ids}
    p_cons_hist = {b: [] for b in building_ids}
    served_ids = set()

    for _ in range(scenario['T']):
        state = sim.get_state()
        decisions = scheduler.decide(state)

        due_arcs = {(d['i_d'], d['j_d']): d['id'] for d in state['demands']}
        for dec in decisions['fleet']:
            if dec['arc'] in due_arcs:
                served_ids.add(due_arcs[dec['arc']])

        sim.step(decisions)

        t = state['t']
        for b in sim.buildings.buildings:
            p_load_hist[b.b_id].append(scenario['load_profile'].get(t, 0.0))
            p_grid_hist[b.b_id].append(b.p_grid)
            p_cons_hist[b.b_id].append(b.p_cons)
        for b_id, v in sim.p_v2b.items():
            p_v2b_hist[b_id].append(v)

    all_demands = list(scenario['ride_demand'].demands)
    served = [d for d in all_demands if d['id'] in served_ids]
    rho = metrics.demand_fulfillment(served, all_demands, scenario['network'])

    print(f"\n--- {label} ---")
    for b_id in building_ids:
        dp = metrics.peak_reduction(p_load_hist[b_id], p_grid_hist[b_id])
        eta = metrics.v2b_utilization(p_v2b_hist[b_id], p_cons_hist[b_id])
        print(f"  Building {b_id}: peak_reduction={dp:.2f} kW, v2b_utilization={eta:.2%}")
    print(f"  Fleet: demand_fulfillment (rho) = {rho:.2%} ({len(served)}/{len(all_demands)})")
    return rho


if __name__ == '__main__':
    scenario_heur = build_scenario()
    scenario_milp = build_scenario()  # separate fresh objects -- Simulator mutates fleet/buildings

    print("Solving MILP (this can take a few minutes)...")
    milp_scheduler = MILPScheduler(scenario_milp, time_limit=300)
    print("MILP solved.")

    heuristic_scheduler = HeuristicScheduler()

    run_scheduler(scenario_heur, heuristic_scheduler, "HeuristicScheduler")
    run_scheduler(scenario_milp, milp_scheduler, "MILPScheduler (day-ahead, lambda=1.0)")
