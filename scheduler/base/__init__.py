from abc import ABC, abstractmethod


class BaseScheduler(ABC):
    @abstractmethod
    def decide(self, state: dict) -> dict:
        """
        Input:  state from Simulator.get_state() —
            't', 'demands', 'fleet', 'buildings', 'network',
            and 'p_v2b': {b_id: kW}, the V2B power realized at each
            building as of the end of the previous timestep. Available
            for any scheduler to use or ignore; not required.

        Output: {
            'fleet':     [{'arc': (i,j) | None, 'p': float}, ...],  one per vehicle
            'buildings': {b_id: t_sp_float | None},                 temperature setpoint,
                         or None for "no thermal decision" -- Building.step() then skips
                         the HVAC relay entirely (p_hvac stays 0) rather than treating
                         None as some particular temperature. Mode A buildings (rc=None)
                         ignore t_sp either way, so this distinction only matters for
                         Mode B (thermal-aware) buildings.
        }
        """


class NullScheduler(BaseScheduler):
    def decide(self, state):
        return {
            'fleet': [{'arc': None, 'p': 0.0} for _ in state['fleet']],
            # None, not a fixed setpoint like 24.0 -- "null" means no decision
            # anywhere, fleet or building. A fixed setpoint would still make
            # Mode B buildings run real HVAC (bang-bang relay chasing 24.0),
            # which isn't "doing nothing," it's a specific thermal policy.
            'buildings': {b['b_id']: None for b in state['buildings']},
        }
