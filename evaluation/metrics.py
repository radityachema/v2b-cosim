"""Evaluation metrics -- physical units only, no monetary conversions."""
import statistics


def peak_reduction(p_load_history, p_grid_history):
    """Delta P (kW)."""
    return max(p_load_history) - max(p_grid_history)


def v2b_utilization(p_v2b_history, p_cons_history):
    """Eta v2b: fraction of offered V2B power actually consumed [0, 1]."""
    offered = sum(p_v2b_history)
    if offered == 0:
        return 0.0
    return sum(p_cons_history) / offered


def temporal_alignment(p_v2b_history, p_load_history):
    """Phi_i: Pearson correlation between fleet V2B availability and building load.
    Returns 0.0 if either series is constant (correlation undefined)."""
    if len(p_v2b_history) < 2 or len(set(p_v2b_history)) < 2 or len(set(p_load_history)) < 2:
        return 0.0
    return statistics.correlation(p_v2b_history, p_load_history)


def demand_fulfillment(served_demands, all_demands, network):
    """Rho: distance-weighted fraction of ride-hailing demand served [0, 1].

    Distance is derived from the network, not stored on the demand --
    consistent with RideDemandClass's own convention.
    """
    total_dist = sum(network.get_arc(d['i_d'], d['j_d'])['d'] for d in all_demands)
    if total_dist == 0:
        return 1.0
    served_dist = sum(network.get_arc(d['i_d'], d['j_d'])['d'] for d in served_demands)
    return served_dist / total_dist
