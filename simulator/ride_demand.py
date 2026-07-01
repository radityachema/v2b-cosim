class RideDemandClass:
    def __init__(self, demands):
        self.demands = demands

    def get_at(self, t):
        return [d for d in self.demands if d['t_d'] == t]
