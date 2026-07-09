from scheduler.base import BaseScheduler


class HeuristicScheduler(BaseScheduler):
    """Constrained opportunistic discharge rule. See README.md (Algorithm 1)."""

    S_RESERVE = 0.2  # TODO: derive from literature -- see README.md

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
            if v['arc'] is not None:                          # mid-transit
                decisions.append({'arc': None, 'p': 0.0})
                continue

            node = v['node']
            candidates = [d for d in demands_by_origin.get(node, []) if d['id'] not in claimed]
            if candidates:                                     # serve a ride
                d = candidates[0]
                claimed.add(d['id'])
                decisions.append({'arc': (d['i_d'], d['j_d']), 'p': 0.0})
                continue

            if node not in building_nodes:                     # -> nearest building
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

            if v['soc'] >= self.S_RESERVE:                     # discharge (V2B)
                decisions.append({'arc': None, 'p': -v['p_max']})
            else:                                               # charge
                decisions.append({'arc': None, 'p': v['p_max']})

        return decisions

    def _decide_buildings(self, state):
        return {b['b_id']: None for b in state['buildings']}   # constant -- see README.md
