class RideDemandClass:
    def __init__(self, demands):
        self.demands = demands #in disctionary with 'id','from_id','to_id','time_d'

    def get_at(self, t):
        return [d for d in self.demands if d['t_d'] == t]
