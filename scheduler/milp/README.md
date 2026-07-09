# MILPScheduler

Day-ahead joint routing + V2B dispatch MILP, solved once at construction. No thermal term -- matches the original notation's scope, not a reduction from it.

## Notation

| Symbol | Meaning |
|---|---|
| $\mathcal{T} = \{0,\ldots,T-1\}$ | discrete timesteps, duration $\Delta t$ |
| $\mathcal{N}$, $\mathcal{N}^B \subseteq \mathcal{N}$ | network nodes; building nodes |
| $\mathcal{V}$, $\mathcal{D}$, $\mathcal{D}_t$ | vehicles; ride demands; demands with pickup at $t$ |
| $c \in \mathcal{N}$ | depot node |
| $i_d, j_d, t_d, \ell_d$ | demand $d$'s origin, destination, pickup time, distance |
| $\tau_{ij}$, $e_{ij}$ | travel time and SoC fraction consumed on arc $(i,j)$ |
| $E^{cap}$, $\bar{P}$ | battery capacity; max charge/discharge power per vehicle |
| $S^{min}$, $S^{max}$, $S^{init}$ | SoC operating bounds and initial value |
| $P^L_{i,t}$ | baseline load of building $i$ at $t$ |
| $Q^{bldg}$ | aggregate charger power capacity at a building node |
| $\lambda \in [0,1]$ | minimum distance-weighted demand-service level |
| $M$ | big-M constant, $= \max_{i \neq j} \tau_{ij} + 10$ |

## Model 1 -- MILPScheduler

**Variables**

- $x_{v,i,j,t} \in \{0,1\}$ -- 1 if vehicle $v$ occupies arc $(i,j)$ at $t$, every period of a multi-step trip, not just departure. Self-loop $i=j$ = stationary at $i$.
- $y_{v,d} \in \{0,1\}$ -- 1 if vehicle $v$ is assigned to demand $d$
- $P_{v,i,t} \in \mathbb{R}$ -- signed power, vehicle $v$ at building $i$, $t$; $+$ charges, $-$ discharges (V2B)
- $S_{v,t} \in [S^{min}, S^{max}]$ -- SoC of vehicle $v$ at the start of period $t$
- $Z^{peak} \geq 0$ -- worst-case building net load across all buildings, all $t$
- $dep_{v,i,j,t} \in \{0,1\}$ -- 1 iff $v$ departs on $(i,j)$ at exactly $t$, derived from $x$ (Constraint 6)

**Objective**

$$\min\ Z^{peak}$$

**Constraints**

1. Single state -- $\sum_{i,j \in \mathcal{N}} x_{v,i,j,t} = 1 \quad \forall v,t$
2. Flow conservation -- $x_{v,i,j,t} \leq x_{v,i,j,t+1} + \sum_k x_{v,j,k,t+1} \quad \forall v,i,j,\ t<T-1$
3. Transit duration
   $$\sum_{k=t}^{t+\tau_{ij}} x_{v,i,j,k} \leq \tau_{ij} + M\big(1-(x_{v,i,j,t}-x_{v,i,j,t-1})\big)$$
   $$\sum_{k=t}^{t+\tau_{ij}} x_{v,i,j,k} \geq \tau_{ij} - M\big(1-(x_{v,i,j,t}-x_{v,i,j,t-1})\big)$$
   $\forall v \in \mathcal{V},\ \forall i,j \in \mathcal{N}\ (i\neq j),\ \forall t$. Replaces the original's separate Min-transit / Max-transit pair with one big-M mechanism, gated inline on $x_{v,i,j,t}-x_{v,i,j,t-1}$ (1 exactly at a departure, $\leq 0$ otherwise). Deliberately not tied to $dep$ (Constraint 6) -- different purpose, no need to share machinery.
4. Initial position -- $x_{v,c,c,0} = 1 \quad \forall v$
5. Terminal position -- $x_{v,c,c,T-1} = 1 \quad \forall v$
6. Departure indicator  -- $dep_{v,i,j,t} \leq x_{v,i,j,t}$,   $dep_{v,i,j,t} \leq 1-x_{v,i,j,t-1}$,   $dep_{v,i,j,t} \geq x_{v,i,j,t}-x_{v,i,j,t-1}$. Standard AND-linking; not read by any other constraint, only by `MILPScheduler` for a direct per-timestep lookup instead of pattern-matching $x$'s solved trajectory.
7. Peak bounding -- $Z^{peak} \geq P^L_{i,t} + \sum_v P_{v,i,t} \quad \forall i \in \mathcal{N}^B, t$
8. SoC initialization -- $S_{v,0} = S^{init} \quad \forall v$
9. SoC terminal recovery  -- $S_{v,T} \geq S^{init} \quad \forall v$. Fleet must end the horizon at least as charged as it started -- not in the original, which only bounded SoC within $[S^{min}, S^{max}]$.
10. SoC dynamics -- $S_{v,t+1} = S_{v,t} + \sum_{i \in \mathcal{N}^B} P_{v,i,t}\Delta t / E^{cap} - \sum_{i,j} x_{v,i,j,t}\cdot(e_{ij}/\tau_{ij}) \quad \forall v,t$
11. Power linkage -- $-\bar{P}\cdot x_{v,i,i,t} \leq P_{v,i,t} \leq \bar{P}\cdot x_{v,i,i,t} \quad \forall v, i \in \mathcal{N}^B, t$
12. Building charger capacity  -- $-Q^{bldg} \leq \sum_v P_{v,i,t} \leq Q^{bldg} \quad \forall i \in \mathcal{N}^B, t$. Aggregate power at a building node is capped by installed charger hardware, independent of how many vehicles happen to be parked there -- distinct from the per-vehicle $\bar{P}$ cap in Constraint 11.
13. Ride-route coupling  -- $y_{v,d} \leq x_{v,i_d,j_d,t_d}$,   $y_{v,d} \leq 1 - x_{v,i_d,j_d,t_d-1}$ $\quad \forall v,d$. Same binding behavior as the original's single inequality $y_{v,d} \leq x_{t_d} - x_{t_d-1}$, implemented as two upper bounds.
14. Ride assignment -- $\sum_v y_{v,d} \leq 1 \quad \forall d$
15. Vehicle capacity -- $\sum_{d \in \mathcal{D}_t} y_{v,d} \leq 1 \quad \forall v,t$
16. Demand fulfillment -- $\sum_v \sum_d y_{v,d}\,\ell_d \geq \lambda \sum_d \ell_d$. Only added when $\lambda>0$ and total requested distance $>0$. Equivalent to the original's $\rho \geq \lambda$ with $\rho$ substituted directly, no separate $\rho$ variable.

**Complexity:** $O(|\mathcal{V}|\cdot|\mathcal{N}|^2\cdot T)$ binary variables dominate ($x$); solved once via Gurobi (MILP, no polynomial-time guarantee), cached to `plan_path` so later constructions load instead of re-solving.

## Notes

- `MILPScheduler` solves this model once (Pyomo + Gurobi) and caches the plan; `decide()` is then a stateless lookup, not a re-solve.
- Unlike the heuristic, the MILP has full-day foresight and a hard demand-service floor $\lambda$ the heuristic has no equivalent of -- both structural advantages, not tuning. Reported comparisons should give peak reduction and demand fulfillment together, never peak reduction alone.

<details>
<summary>LaTeX source (standalone equations)</summary>

```latex
% Sets: T={0,...,T-1}, N, N^B subset N, V, D, D_t subset D, c in N
% Parameters: tau_ij, e_ij, E^cap, Pbar, S^min, S^max, S^init, P^L_{i,t}, Q^bldg, lambda, M

\textbf{Variables}
\begin{align*}
x_{v,i,j,t} &\in \{0,1\} \\
y_{v,d} &\in \{0,1\} \\
P_{v,i,t} &\in \mathbb{R} \\
S_{v,t} &\in [S^{min}, S^{max}] \\
Z^{peak} &\geq 0 \\
dep_{v,i,j,t} &\in \{0,1\}
\end{align*}

\textbf{Objective}
$$\min\ Z^{peak}$$

\textbf{Constraints}
\begin{align}
&\sum_{i,j \in \mathcal{N}} x_{v,i,j,t} = 1 && \forall v,t \label{c:single}\\
&x_{v,i,j,t} \leq x_{v,i,j,t+1} + \sum_{k} x_{v,j,k,t+1} && \forall v,i,j,\ t<T-1 \label{c:flow}\\
&\sum_{k=t}^{t+\tau_{ij}} x_{v,i,j,k} \leq \tau_{ij} + M\big(1-(x_{v,i,j,t}-x_{v,i,j,t-1})\big) && \forall v, i{\neq}j, t \label{c:transit-up}\\
&\sum_{k=t}^{t+\tau_{ij}} x_{v,i,j,k} \geq \tau_{ij} - M\big(1-(x_{v,i,j,t}-x_{v,i,j,t-1})\big) && \forall v, i{\neq}j, t \label{c:transit-lo}\\
&x_{v,c,c,0} = 1 && \forall v \label{c:init}\\
&x_{v,c,c,T-1} = 1 && \forall v \label{c:term}\\
&dep_{v,i,j,t} \leq x_{v,i,j,t},\quad dep_{v,i,j,t} \leq 1-x_{v,i,j,t-1},\quad dep_{v,i,j,t} \geq x_{v,i,j,t}-x_{v,i,j,t-1} && \forall v,i{\neq}j,t \label{c:dep}\\
&Z^{peak} \geq P^L_{i,t} + \sum_{v} P_{v,i,t} && \forall i \in \mathcal{N}^B, t \label{c:peak}\\
&S_{v,0} = S^{init} && \forall v \label{c:soc0}\\
&S_{v,T} \geq S^{init} && \forall v \label{c:socT}\\
&S_{v,t+1} = S_{v,t} + \sum_{i \in \mathcal{N}^B} \frac{P_{v,i,t}\Delta t}{E^{cap}} - \sum_{i,j} x_{v,i,j,t}\frac{e_{ij}}{\tau_{ij}} && \forall v,t \label{c:socdyn}\\
&-\bar{P}\,x_{v,i,i,t} \leq P_{v,i,t} \leq \bar{P}\,x_{v,i,i,t} && \forall v, i \in \mathcal{N}^B, t \label{c:pow}\\
&-Q^{bldg} \leq \sum_{v} P_{v,i,t} \leq Q^{bldg} && \forall i \in \mathcal{N}^B, t \label{c:bldgcap}\\
&y_{v,d} \leq x_{v,i_d,j_d,t_d},\quad y_{v,d} \leq 1 - x_{v,i_d,j_d,t_d-1} && \forall v,d \label{c:couple}\\
&\sum_{v} y_{v,d} \leq 1 && \forall d \label{c:assign}\\
&\sum_{d \in \mathcal{D}_t} y_{v,d} \leq 1 && \forall v,t \label{c:vcap}\\
&\sum_{v}\sum_{d} y_{v,d}\,\ell_d \geq \lambda \sum_{d} \ell_d \label{c:fulfill}
\end{align}
```
