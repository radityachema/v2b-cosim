class Vehicle:
    def __init__(self, v_id, soc_init, e_cap, p_max, s_min, s_max):
        self.v_id = v_id
        self.soc = soc_init
        self.node = None        # set by Simulator at init (network.depot)
        self.arc = None         # (i, j) while traveling
        self.arc_remaining = 0  # timesteps until arrival
        self.p = 0.0
        self.e_cap = e_cap
        self.p_max = p_max
        self.s_min = s_min
        self.s_max = s_max

    @property
    def state(self):
        return {
            'v_id': self.v_id,
            'soc': self.soc,
            'node': self.node,
            'arc': self.arc,
            'p': self.p,
            'p_max': self.p_max,
            's_min': self.s_min,
            's_max': self.s_max,
            'e_cap': self.e_cap,
        }

    def step(self, decision, network, dt):
        if self.arc is not None:
            arc_info = network.get_arc(*self.arc)
            self.soc -= arc_info['e'] / arc_info['tau']
            self.soc = max(self.s_min, min(self.s_max, self.soc))  # floors at s_min -- trip cost isn't pre-checked
            self.arc_remaining -= 1
            if self.arc_remaining == 0:
                self.node = self.arc[1]
                self.arc = None
            self.p = 0.0
        else:
            new_arc = decision.get('arc')
            if new_arc is not None and new_arc[0] != self.node:
                new_arc = None  # scheduler issued an arc not starting from this vehicle's actual
                                 # node -- physically impossible, clamp to "no decision" same as
                                 # any other hardware limit (see p_max/SoC clamping below)
            if new_arc is not None:
                arc_info = network.get_arc(*new_arc)
                self.node = None
                self.arc = new_arc
                self.arc_remaining = arc_info['tau']
                self.p = 0.0
                self.soc -= arc_info['e'] / arc_info['tau']
                self.soc = max(self.s_min, min(self.s_max, self.soc))
                self.arc_remaining -= 1
                if self.arc_remaining == 0:
                    self.node = self.arc[1]
                    self.arc = None
            else:
                self.p = max(-self.p_max, min(self.p_max, decision.get('p', 0.0)))
                self.soc += self.p * dt / self.e_cap
                self.soc = max(self.s_min, min(self.s_max, self.soc))


class FleetClass:
    def __init__(self, vehicles):
        self.vehicles = vehicles

    @property
    def state(self):
        return [v.state for v in self.vehicles]

    def step(self, decisions, network, dt):
        for v, dec in zip(self.vehicles, decisions):
            v.step(dec, network, dt)
