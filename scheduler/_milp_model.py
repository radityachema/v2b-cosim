"""
Pure Pyomo model builder for the day-ahead joint routing + V2B dispatch +
thermal MILP. No knowledge of this repo's Simulator/Scheduler classes --
plain dicts/lists in, plain result dict out.

Variables: x[v,i,j,t] (binary, 1 if vehicle v occupies arc (i,j) during
timestep t -- including every timestep of a multi-step trip, not just
departure), y[v,d] (binary, 1 if vehicle v serves demand d), P[v,i,t]
(continuous signed power, vehicle v at building i, + = charging), S[v,t]
(continuous SoC), Z_peak (the objective: minimize the worst building
peak across all buildings and timesteps).

dep[v,i,j,t] is an added binary variable, 1 only at the exact timestep
a vehicle departs on arc (i,j), derived from `x` via a standard
AND-linking constraint (not detected by pattern-matching after solving).
This is what MILPScheduler reads to build a per-timestep decision -- a
direct lookup, not a search over the solved `x` trajectory. `x` itself
represents "occupying the arc" (needed for the SoC/transit-duration
constraints), which doesn't directly tell you "did the vehicle just
depart this timestep" -- `dep` answers that question directly.

Network numbers (e, tau) are pulled from the actual NetworkClass instance
passed in, never recomputed independently -- single source of truth with
whatever Simulator will replay the plan through.
"""
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
    load_profile, rc_params, T, dt, E_cap, P_bar, S_min, S_max, S_init,
    Q_bldg, lam, t_min=20.0, t_max=26.0, t_out=30.0,
    time_limit=300, verbose=False,
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

    # -- departure variable: 1 only at the exact onset timestep of arc (i,j) --
    def _dep_idx(m):
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

    # -- thermal extension --
    m.t_in = pyo.Var(m.NB, pyo.RangeSet(0, T), domain=pyo.Reals)
    m.z = pyo.Var(m.NB, m.TT, domain=pyo.Binary)
    m.p_hvac = pyo.Var(m.NB, m.TT, domain=pyo.NonNegativeReals)

    m.c_phvac = pyo.Constraint(m.NB, m.TT,
        rule=lambda m, i, t: m.p_hvac[i, t] == rc_params[i]['hvac_max'] * m.z[i, t])

    m.c_tin_init = pyo.Constraint(m.NB,
        rule=lambda m, i: m.t_in[i, 0] == rc_params[i]['t_init'])

    def c_tin_dyn(m, i, t):
        a_i, b_i = rc_params[i]['a'], rc_params[i]['b']
        return m.t_in[i, t + 1] == (1 - a_i) * m.t_in[i, t] + a_i * t_out - b_i * m.p_hvac[i, t]
    m.c_tin_dyn = pyo.Constraint(m.NB, m.TT, rule=c_tin_dyn)

    m.c_comfort_lo = pyo.Constraint(m.NB, pyo.RangeSet(0, T),
        rule=lambda m, i, t: m.t_in[i, t] >= t_min)
    m.c_comfort_hi = pyo.Constraint(m.NB, pyo.RangeSet(0, T),
        rule=lambda m, i, t: m.t_in[i, t] <= t_max)

    # Peak must include HVAC draw -- required, not optional: otherwise the
    # thermal extension wouldn't count toward the peak it's supposed to shave.
    # load_profile is per-building ({b_id: {t: kW}}) -- buildings can have
    # genuinely different real load curves, not one shared synthetic profile.
    m.c_peak = pyo.Constraint(m.NB, m.TT,
        rule=lambda m, i, t: m.Zpeak >= load_profile[i][t] + m.p_hvac[i, t]
                                        + sum(m.P[v, i, t] for v in m.V))

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
    result = solver.solve(m, tee=verbose)

    status = str(result.solver.status)
    term = str(result.solver.termination_condition)

    return {
        'model': m,
        'status': status,
        'termination': term,
        'nodes': nodes,
        'building_nodes': list(building_nodes),
        'vehicles_list': list(vehicles_list),
        'T': T,
    }
