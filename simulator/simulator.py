class Simulator:
    def __init__(self, network, ride_demand, fleet, buildings, dt=0.25):
        self.network = network
        self.ride_demand = ride_demand
        self.fleet = fleet
        self.buildings = buildings
        self.dt = dt
        self.t = 0
        for v in self.fleet.vehicles:
            v.node = network.depot

    def get_state(self):
        return {
            't': self.t,
            'demands': self.ride_demand.get_at(self.t),
            'fleet': self.fleet.state,
            'buildings': self.buildings.state,
            'network': {
                'building_nodes': self.network.building_nodes,
                'arcs': self.network.arcs,
                'depot': self.network.depot,
            },
        }

    def step(self, decisions):
        self.fleet.step(decisions.get('fleet', []), self.network, self.dt)
        p_v2b = self._compute_p_v2b()
        p_hvac_map = {
            b_id: dec.get('p_hvac', 0.0)
            for b_id, dec in decisions.get('buildings', {}).items()
        }
        self.buildings.step(self.t, p_v2b, p_hvac_map)
        self.t += 1

    def _compute_p_v2b(self):
        p_max_global = max((v.p_max for v in self.fleet.vehicles), default=0.0)
        result = {}
        for b in self.buildings.buildings:
            discharge = sum(
                max(0.0, -v.p)
                for v in self.fleet.vehicles
                if v.arc is None and v.node == b.b_id
            )
            result[b.b_id] = min(discharge, b.n_chargers * p_max_global)
        return result
