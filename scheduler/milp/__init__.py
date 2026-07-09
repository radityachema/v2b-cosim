"""Day-ahead MILP scheduler: solve once, decide() is a stateless lookup. See README.md (Model 1)."""
import pickle
from pathlib import Path

import pyomo.environ as pyo

from scheduler.base import BaseScheduler
from scheduler.milp._model import build_and_solve_extended


class MILPScheduler(BaseScheduler):
    def __init__(self, scenario, time_limit=300, verbose=False, plan_path=None):
        if plan_path is not None and Path(plan_path).exists():  # cached plan -- skip re-solve
            with open(plan_path, 'rb') as f:
                plan = pickle.load(f)
            self._T = plan['T']
            self._building_nodes = plan['building_nodes']
            self._fleet_plan = plan['fleet_plan']
            return

        result = build_and_solve_extended(
            network=scenario['network'],
            vehicles_list=scenario['vehicles_list'],
            building_nodes=scenario['building_nodes'],
            depot=scenario['depot'],
            demands_milp=scenario['demands_milp'],
            load_profile=scenario['load_profile'],
            T=scenario['T'],
            dt=scenario['dt'],
            E_cap=scenario['E_cap'],
            P_bar=scenario['P_bar'],
            S_min=scenario['S_min'],
            S_max=scenario['S_max'],
            S_init=scenario['S_init'],
            Q_bldg=scenario['Q_bldg'],
            lam=scenario['lam'],
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
        self._fleet_plan = self._extract_fleet_plan(m, scenario)

        if plan_path is not None:
            with open(plan_path, 'wb') as f:
                pickle.dump({
                    'T': self._T,
                    'building_nodes': self._building_nodes,
                    'fleet_plan': self._fleet_plan,
                }, f)

    def decide(self, state):
        t = state['t']
        fleet = [
            self._fleet_plan.get((v['v_id'], t), {'arc': None, 'p': 0.0})
            for v in state['fleet']
        ]
        buildings = {b['b_id']: None for b in state['buildings']}  # no thermal decision -- see README.md
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
