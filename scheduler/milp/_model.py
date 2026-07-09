"""Pyomo model builder for the day-ahead routing + V2B dispatch MILP. See README.md (Model 1)."""
import pyomo.environ as pyo


def _e_hat(network, i, j):
    if i == j:
        return 0.0
    arc = network.get_arc(i, j)
    return arc['e'] / arc['tau']


def _tau(network, i, j):
    if i == j:
        return 0
    return network.get_arc(i, j)['tau']


def build_and_solve_extended(
    network, vehicles_list, building_nodes, depot, demands_milp,
    load_profile, T, dt, E_cap, P_bar, S_min, S_max, S_init,
    Q_bldg, lam, time_limit=300, verbose=False,
):
    nodes = list(network.nodes)
    m = pyo.ConcreteModel()
    m.V = pyo.Set(initialize=vehicles_list)
    m.N = pyo.Set(initialize=nodes)
    m.NB = pyo.Set(initialize=building_nodes)
    m.TT = pyo.RangeSet(0, T - 1)
    m.D = pyo.Set(initialize=demands_milp.keys())

    m.x = pyo.Var(m.V, m.N, m.N, m.TT, domain=pyo.Binary)
    m.y = pyo.Var(m.V, m.D, domain=pyo.Binary)
    m.P = pyo.Var(m.V, m.NB, m.TT, domain=pyo.Reals)
    m.S = pyo.Var(m.V, pyo.RangeSet(0, T), bounds=(S_min, S_max))
    m.Zpeak = pyo.Var(domain=pyo.NonNegativeReals)

    m.obj = pyo.Objective(expr=m.Zpeak, sense=pyo.minimize)

    m.c_single = pyo.Constraint(m.V, m.TT,
        rule=lambda m, v, t: sum(m.x[v, i, j, t] for i in m.N for j in m.N) == 1)

    def c_flow(m, v, i, j, t):
        if t >= T - 1:
            return pyo.Constraint.Skip
        return m.x[v, i, j, t] <= m.x[v, i, j, t + 1] + sum(m.x[v, j, k, t + 1] for k in m.N)
    m.c_flow = pyo.Constraint(m.V, m.N, m.N, m.TT, rule=c_flow)

    def _bigm_idx(m):
        for v in m.V:
            for i in m.N:
                for j in m.N:
                    if i == j:
                        continue
                    tau_ij = _tau(network, i, j)
                    for t in range(1, T):
                        if t + tau_ij <= T - 1:
                            yield (v, i, j, t)
    m.bigm_idx = pyo.Set(dimen=4, initialize=_bigm_idx)
    M_val = max(_tau(network, i, j) for i in nodes for j in nodes if i != j) + 10

    m.c_bigm_upper = pyo.Constraint(m.bigm_idx,
        rule=lambda m, v, i, j, t:
            sum(m.x[v, i, j, k] for k in range(t, t + _tau(network, i, j) + 1))
            <= _tau(network, i, j) + M_val * (1 - (m.x[v, i, j, t] - m.x[v, i, j, t - 1])))
    m.c_bigm_lower = pyo.Constraint(m.bigm_idx,
        rule=lambda m, v, i, j, t:
            sum(m.x[v, i, j, k] for k in range(t, t + _tau(network, i, j) + 1))
            >= _tau(network, i, j) - M_val * (1 - (m.x[v, i, j, t] - m.x[v, i, j, t - 1])))

    m.c_init = pyo.Constraint(m.V, rule=lambda m, v: m.x[v, depot, depot, 0] == 1)
    m.c_term = pyo.Constraint(m.V, rule=lambda m, v: m.x[v, depot, depot, T - 1] == 1)

    def _dep_idx(m):  # dep[v,i,j,t]: 1 only at departure onset -- see README.md (Constraint 6)
        for v in m.V:
            for i in m.N:
                for j in m.N:
                    if i != j:
                        for t in m.TT:
                            yield (v, i, j, t)
    m.dep_idx = pyo.Set(dimen=4, initialize=_dep_idx)
    m.dep = pyo.Var(m.dep_idx, domain=pyo.Binary)

    def c_dep_upper1(m, v, i, j, t):
        return m.dep[v, i, j, t] <= m.x[v, i, j, t]
    def c_dep_upper2(m, v, i, j, t):
        x_prev = m.x[v, i, j, t - 1] if t >= 1 else 0
        return m.dep[v, i, j, t] <= 1 - x_prev
    def c_dep_lower(m, v, i, j, t):
        x_prev = m.x[v, i, j, t - 1] if t >= 1 else 0
        return m.dep[v, i, j, t] >= m.x[v, i, j, t] - x_prev
    m.c_dep_upper1 = pyo.Constraint(m.dep_idx, rule=c_dep_upper1)
    m.c_dep_upper2 = pyo.Constraint(m.dep_idx, rule=c_dep_upper2)
    m.c_dep_lower = pyo.Constraint(m.dep_idx, rule=c_dep_lower)

    m.c_peak = pyo.Constraint(m.NB, m.TT,  # no HVAC term -- see README.md
        rule=lambda m, i, t: m.Zpeak >= load_profile[i][t] + sum(m.P[v, i, t] for v in m.V))

    m.c_soc_init = pyo.Constraint(m.V, rule=lambda m, v: m.S[v, 0] == S_init)

    def c_soc(m, v, t):
        chg = sum(m.P[v, i, t] * dt / E_cap for i in m.NB)
        drv = sum(m.x[v, i, j, t] * _e_hat(network, i, j) for i in m.N for j in m.N)
        return m.S[v, t + 1] == m.S[v, t] + chg - drv
    m.c_soc_dyn = pyo.Constraint(m.V, m.TT, rule=c_soc)
    m.c_soc_term = pyo.Constraint(m.V, rule=lambda m, v: m.S[v, T] >= S_init)

    m.c_pow_up = pyo.Constraint(m.V, m.NB, m.TT,
        rule=lambda m, v, i, t: m.P[v, i, t] <= P_bar * m.x[v, i, i, t])
    m.c_pow_lo = pyo.Constraint(m.V, m.NB, m.TT,
        rule=lambda m, v, i, t: m.P[v, i, t] >= -P_bar * m.x[v, i, i, t])

    m.c_bldg_up = pyo.Constraint(m.NB, m.TT,
        rule=lambda m, i, t: sum(m.P[v, i, t] for v in m.V) <= Q_bldg)
    m.c_bldg_lo = pyo.Constraint(m.NB, m.TT,
        rule=lambda m, i, t: sum(m.P[v, i, t] for v in m.V) >= -Q_bldg)

    def c_couple_on(m, v, d):
        o, dest, td, _ = demands_milp[d]
        return m.y[v, d] <= m.x[v, o, dest, td]
    def c_couple_new(m, v, d):
        o, dest, td, _ = demands_milp[d]
        x_prev = m.x[v, o, dest, td - 1] if td >= 1 else 0
        return m.y[v, d] <= 1 - x_prev
    m.c_couple_on = pyo.Constraint(m.V, m.D, rule=c_couple_on)
    m.c_couple_new = pyo.Constraint(m.V, m.D, rule=c_couple_new)

    m.c_assign = pyo.Constraint(m.D,
        rule=lambda m, d: sum(m.y[v, d] for v in m.V) <= 1)

    def c_vcap(m, v, t):
        dd = [d for d in demands_milp if demands_milp[d][2] == t]
        if not dd:
            return pyo.Constraint.Skip
        return sum(m.y[v, d] for d in dd) <= 1
    m.c_vcap = pyo.Constraint(m.V, m.TT, rule=c_vcap)

    total_dist = sum(demands_milp[d][3] for d in demands_milp)
    if lam > 0 and total_dist > 0:
        m.c_fulfill = pyo.Constraint(
            expr=sum(m.y[v, d] * demands_milp[d][3] for v in vehicles_list for d in demands_milp)
                 >= lam * total_dist)

    solver = pyo.SolverFactory('gurobi')
    solver.options['TimeLimit'] = time_limit
    result = solver.solve(m, tee=verbose, load_solutions=False)  # load_solutions=False -- see README.md

    status = str(result.solver.status)
    term = str(result.solver.termination_condition)
    upper = result.problem[0]['Upper bound'] if result.problem else None
    has_incumbent = upper is not None and upper == upper and abs(upper) != float('inf')  # upper==upper: not NaN; incumbent, not proven-optimal -- see README.md

    if has_incumbent:
        m.solutions.load_from(result)
        if term != str(pyo.TerminationCondition.optimal):
            lower = result.problem[0]['Lower bound']
            gap = abs(upper - lower) / abs(upper) if upper else 0.0
            print(f"MILP: time_limit={time_limit}s reached before proving optimality "
                  f"(status={status}, termination={term}) -- using best incumbent "
                  f"found: {upper:.4f} (gap {gap:.2%} vs. proven bound {lower:.4f}).")
    else:
        bound = result.problem[0]['Lower bound'] if result.problem else None  # Gurobi's best proven bound (BestBd)
        raise RuntimeError(
            f"MILP found no feasible solution within time_limit={time_limit}s "
            f"(status={status}, termination={term}, best_bound={bound}). "
            f"Try a longer time_limit, or a less strict demand-service floor (lam)."
        )

    return {
        'model': m,
        'status': status,
        'termination': term,
        'nodes': nodes,
        'building_nodes': list(building_nodes),
        'vehicles_list': list(vehicles_list),
        'T': T,
    }
