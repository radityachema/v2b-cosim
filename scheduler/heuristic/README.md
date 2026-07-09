# HeuristicScheduler

Constrained opportunistic discharge rule (fleet); constant, undecided setpoint (buildings).

## Notation

| Symbol | Meaning |
|---|---|
| $\mathcal{V}$ | fleet -- set of vehicles |
| $\mathcal{N}^B \subseteq \mathcal{N}$ | building nodes |
| $\mathcal{D}$, $\mathcal{D}_t \subseteq \mathcal{D}$ | ride demands; $\mathcal{D}_t$ = due at timestep $t$ |
| $S_{v,t}$ | SoC of vehicle $v$ at start of period $t$ |
| $node_v(t)$, $arc_v(t)$ | vehicle $v$'s position at $t$ -- stationary at a node, or mid-transit on an arc |
| $\bar{P}_v$ | vehicle $v$'s rated power (max magnitude, charge or discharge) |
| $\tau_{ij}$ | travel time on arc $(i,j)$, in timesteps |
| $S^{res}$ | fixed SoC reserve floor (`S_RESERVE` in code) |

## Algorithm 1 -- HeuristicScheduler.decide

```
Require: fleet state {(S_v,t, node_v(t), arc_v(t), P̄_v)}_v in V, demands D_t,
         building nodes N^B, travel times {tau_ij}, reserve floor S^res
Ensure:  fleet decisions {(arc_v(t), p_v(t))}_v in V;
         building setpoints {t_sp_b(t)}_b in N^B

Claimed <- {}
for v in V:                                                  # vehicle order fixes claim priority
    if arc_v(t) != None:                                      # mid-transit
        (arc_v(t), p_v(t)) <- (None, 0)
    elif exists d in D_t : d.origin = node_v(t) and d.id not in Claimed:
        d <- first such demand                                # serve a ride
        Claimed <- Claimed U {d.id}
        (arc_v(t), p_v(t)) <- ((d.origin, d.dest), 0)
    elif node_v(t) not in N^B:
        b* <- argmin_{b in N^B : (node_v(t),b) exists} tau_{node_v(t),b}   # nearest building
        (arc_v(t), p_v(t)) <- ((node_v(t), b*), 0) if b* exists else (None, 0)
    elif S_v,t >= S^res:
        (arc_v(t), p_v(t)) <- (None, -P̄_v)                    # discharge (V2B)
    else:
        (arc_v(t), p_v(t)) <- (None, +P̄_v)                    # charge

t_sp_b(t) <- None  for all b in N^B                           # no thermal decision -- constant
return {(arc_v(t), p_v(t))}_v in V, {t_sp_b(t)}_b in N^B
```

Equivalently, the dispatch case at a building node (matches the case-statement form in `cosim_architecture_math.md`):

$$P_{v,i,t} = \begin{cases} -\bar{P}_v & \text{if } S_{v,t} \geq S^{res} \quad \text{(discharge → V2B)} \\ +\bar{P}_v & \text{if } S_{v,t} < S^{res} \quad \text{(charge)} \end{cases} \qquad i = node_v(t) \in \mathcal{N}^B$$

**Complexity:** $O(|\mathcal{V}| \cdot (|\mathcal{D}_t| + |\mathcal{N}^B|))$ per timestep -- demand lookup is amortized $O(1)$ via an origin-grouped index (`_decide_fleet`); the nearest-building search is a linear scan over $\mathcal{N}^B$.


<details>
<summary>LaTeX source (algorithm + algpseudocode)</summary>

```latex
\begin{algorithm}[t]
\caption{HeuristicScheduler: constrained opportunistic discharge rule}
\label{alg:heuristic}
\begin{algorithmic}[1]
\Require Fleet state $\{(S_{v,t}, node_v(t), arc_v(t), \bar{P}_v)\}_{v \in \mathcal{V}}$,
         demands due now $\mathcal{D}_t$, building nodes $\mathcal{N}^B$,
         arc travel times $\{\tau_{ij}\}$, reserve floor $S^{res}$
\Ensure Fleet decisions $\{(arc_v(t), p_v(t))\}_{v \in \mathcal{V}}$;
        building setpoints $\{t^{sp}_b(t)\}_{b \in \mathcal{N}^B}$
\State $\mathit{Claimed} \gets \emptyset$
\For{$v \in \mathcal{V}$} \Comment{one pass, vehicle order fixes claim priority}
    \If{$arc_v(t) \neq \varnothing$} \Comment{mid-transit}
        \State $(arc_v(t), p_v(t)) \gets (\varnothing, 0)$
    \ElsIf{$\exists\, d \in \mathcal{D}_t : d.\mathit{origin} = node_v(t) \land d.\mathit{id} \notin \mathit{Claimed}$}
        \State $d \gets$ first such demand \Comment{serve a ride}
        \State $\mathit{Claimed} \gets \mathit{Claimed} \cup \{d.\mathit{id}\}$
        \State $(arc_v(t), p_v(t)) \gets ((d.\mathit{origin}, d.\mathit{dest}),\ 0)$
    \ElsIf{$node_v(t) \notin \mathcal{N}^B$}
        \State $b^\star \gets \arg\min_{b \in \mathcal{N}^B\,:\,(node_v(t),b)\ \text{exists}} \tau_{node_v(t), b}$
        \Comment{nearest building}
        \State $(arc_v(t), p_v(t)) \gets \big((node_v(t), b^\star),\ 0\big)$ if $b^\star$ exists, else $(\varnothing, 0)$
    \ElsIf{$S_{v,t} \geq S^{res}$}
        \State $(arc_v(t), p_v(t)) \gets (\varnothing,\ -\bar{P}_v)$ \Comment{discharge (V2B)}
    \Else
        \State $(arc_v(t), p_v(t)) \gets (\varnothing,\ +\bar{P}_v)$ \Comment{charge}
    \EndIf
\EndFor
\State $t^{sp}_b(t) \gets \varnothing \quad \forall b \in \mathcal{N}^B$
\Comment{no thermal decision -- constant, out of scope for this paper}
\State \Return $\{(arc_v(t), p_v(t))\}_{v \in \mathcal{V}}$, $\{t^{sp}_b(t)\}_{b \in \mathcal{N}^B}$
\end{algorithmic}
\end{algorithm}
```
