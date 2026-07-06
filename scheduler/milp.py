"""
MILPScheduler -- day-ahead, pre-solved comparison scheduler. Solves the
entire horizon once at construction (Pyomo + Gurobi), then decide() is a
stateless O(1) lookup into the pre-solved plan. Not the paper's main
method -- a comparison baseline against HeuristicScheduler on identical
scenario data. Works with any scenario dict that carries the fields
`build_and_solve_extended()` needs (see scheduler/_milp_model.py) --
scenarios/real_scenario.py and scenarios/chicago_scenario.py both do.
"""
import pyomo.environ as pyo

from scheduler.base import BaseScheduler
from scheduler._milp_model import build_and_solve_extended


class MILPScheduler(BaseScheduler):
    def __init__(self, scenario, time_limit=300, verbose=False):
        result = build_and_solve_extended(
            network=scenario['network'],
            vehicles_list=scenario['vehicles_list'],
            building_nodes=scenario['building_nodes'],
            depot=scenario['depot'],
            demands_milp=scenario['demands_milp'],
            load_profile=scenario['load_profile'],
            rc_params=scenario['rc_params'],
            T=scenario['T'],
            dt=scenario['dt'],
            E_cap=scenario['E_cap'],
            P_bar=scenario['P_bar'],
            S_min=scenario['S_min'],
            S_max=scenario['S_max'],
            S_init=scenario['S_init'],
            Q_bldg=scenario['Q_bldg'],
            lam=scenario['lam'],
            t_min=scenario['t_min'],
            t_max=scenario['t_max'],
            time_limit=time_limit,
            verbose=verbose,
        )
        m = result['model']
        try:
            pyo.value(m.Zpeak)
        except Exception as e:
            raise RuntimeError(
                f"MILP produced no usable solution "
                f"(status={result['status']}, termination={result['termination']}): {e}"
            )

        self._T = scenario['T']
        self._building_nodes = set(scenario['building_nodes'])
        self._t_sp_min = {
            b: scenario['rc_params'][b].get('t_sp_min', 16.0)
            for b in scenario['building_nodes']
        }
        self._t_sp_max = {
            b: scenario['rc_params'][b].get('t_sp_max', 30.0)
            for b in scenario['building_nodes']
        }
        self._fleet_plan = self._extract_fleet_plan(m, scenario)
        self._building_plan = self._extract_building_plan(m, scenario)

    def decide(self, state):
        t = state['t']
        fleet = [
            self._fleet_plan.get((v['v_id'], t), {'arc': None, 'p': 0.0})
            for v in state['fleet']
        ]
        buildings = {}
        for b in state['buildings']:
            b_id = b['b_id']
            if b_id in self._building_nodes:
                buildings[b_id] = self._building_plan.get(
                    (b_id, t), self._t_sp_max.get(b_id, 30.0))
            else:
                buildings[b_id] = 24.0
        return {'fleet': fleet, 'buildings': buildings}

    def _extract_fleet_plan(self, m, scenario):
        nodes = scenario['nodes']
        building_nodes = self._building_nodes
        plan = {}
        for v in scenario['vehicles_list']:
            for t in range(scenario['T']):
                parked_node = None
                for i in nodes:
                    if pyo.value(m.x[v, i, i, t]) > 0.5:
                        parked_node = i
                        break
                if parked_node is not None:
                    p = pyo.value(m.P[v, parked_node, t]) if parked_node in building_nodes else 0.0
                    plan[(v, t)] = {'arc': None, 'p': p}
                    continue

                departed = None
                for i in nodes:
                    for j in nodes:
                        if i == j:
                            continue
                        if pyo.value(m.dep[v, i, j, t]) > 0.5:
                            departed = (i, j)
                            break
                    if departed is not None:
                        break
                plan[(v, t)] = {'arc': departed, 'p': 0.0} if departed else {'arc': None, 'p': 0.0}
        return plan

    def _extract_building_plan(self, m, scenario):
        plan = {}
        for b in scenario['building_nodes']:
            for t in range(scenario['T']):
                on = pyo.value(m.z[b, t]) > 0.5
                plan[(b, t)] = self._t_sp_min[b] if on else self._t_sp_max[b]
        return plan
