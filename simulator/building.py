class Building:
    def __init__(self, b_id, load_profile, n_chargers, rc=None, weather=None):
        self.b_id = b_id
        # Mode A: pass full BDG2 measured load (HVAC already included)
        # Mode B: pass non-HVAC load only — strip HVAC from BDG2 before passing in
        self.load_profile = load_profile
        self.n_chargers = n_chargers
        self.rc = rc
        self.weather = weather
        self.t_in = rc['t_init'] if rc else None
        self.p_grid = 0.0
        self.p_cons = 0.0

    @property
    def state(self):
        return {
            'b_id': self.b_id,
            't_in': self.t_in,
            'n_chargers': self.n_chargers,
            'p_grid': self.p_grid,
            'p_cons': self.p_cons,
        }

    def step(self, t, p_v2b, p_hvac=0.0):
        p_load = self.load_profile.get(t, 0.0)
        total_load = p_load + p_hvac
        self.p_cons = min(p_v2b, total_load)
        self.p_grid = total_load - self.p_cons

        if self.rc is not None:
            a = self.rc['a']
            b = self.rc['b']
            t_out = (self.weather or {}).get(t, 30.0)
            self.t_in = (1 - a) * self.t_in + a * t_out - b * p_hvac


class BuildingClass:
    def __init__(self, buildings):
        self.buildings = buildings

    @property
    def state(self):
        return [b.state for b in self.buildings]

    def step(self, t, p_v2b_map, p_hvac_map):
        for b in self.buildings:
            b.step(t, p_v2b_map.get(b.b_id, 0.0), p_hvac_map.get(b.b_id, 0.0))
