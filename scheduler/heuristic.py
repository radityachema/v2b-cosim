from scheduler.base import BaseScheduler


class HeuristicScheduler(BaseScheduler):
    """
    Fleet: constrained opportunistic discharge rule.
    Building: thermal pre-conditioning triggered by available DER power.
    """

    # Fixed SoC reserve floor, standing in for the literature's next-trip-energy
    # SoC floor. RideDemandClass.get_at(t) only exposes demands due at the exact
    # current timestep -- there's no forward-demand-assignment mechanism in this
    # codebase to compute a real per-vehicle "next trip" reserve against. A fixed
    # constant is the honest simplification given what's actually available.
    S_RESERVE = 0.2

    T_SP_BASE = 24.0
    T_SP_DELTA = 2.0
    IDLE_T_SP = 24.0  # placeholder for Mode A buildings; ignored by Building.step()

    def decide(self, state):
        return {
            'fleet': self._decide_fleet(state),
            'buildings': self._decide_buildings(state),
        }

    def _decide_fleet(self, state):
        claimed = set()
        demands_by_origin = {}
        for d in state['demands']:
            demands_by_origin.setdefault(d['i_d'], []).append(d)

        building_nodes = state['network']['building_nodes']
        arcs = state['network']['arcs']

        decisions = []
        for v in state['fleet']:
            if v['arc'] is not None:
                decisions.append({'arc': None, 'p': 0.0})
                continue

            node = v['node']
            candidates = [d for d in demands_by_origin.get(node, []) if d['id'] not in claimed]
            if candidates:
                d = candidates[0]
                claimed.add(d['id'])
                decisions.append({'arc': (d['i_d'], d['j_d']), 'p': 0.0})
                continue

            if node not in building_nodes:
                nearest = None
                nearest_tau = None
                for b in building_nodes:
                    arc = arcs.get((node, b))
                    if arc is None:
                        continue
                    if nearest_tau is None or arc['tau'] < nearest_tau:
                        nearest = b
                        nearest_tau = arc['tau']
                if nearest is not None:
                    decisions.append({'arc': (node, nearest), 'p': 0.0})
                else:
                    decisions.append({'arc': None, 'p': 0.0})
                continue

            if v['soc'] >= self.S_RESERVE:
                decisions.append({'arc': None, 'p': -v['p_max']})
            else:
                decisions.append({'arc': None, 'p': v['p_max']})

        return decisions

    def _decide_buildings(self, state):
        p_v2b = state['p_v2b']
        result = {}
        for b in state['buildings']:
            if b['rc'] is None:
                result[b['b_id']] = self.IDLE_T_SP
            elif p_v2b.get(b['b_id'], 0.0) > 0:
                result[b['b_id']] = self.T_SP_BASE - self.T_SP_DELTA
            else:
                result[b['b_id']] = self.T_SP_BASE
        return result
