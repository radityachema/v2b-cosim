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
            'buildings': {b_id: t_sp_float},                        temperature setpoint
        }
        """


class NullScheduler(BaseScheduler):
    def decide(self, state):
        return {
            'fleet': [{'arc': None, 'p': 0.0} for _ in state['fleet']],
            'buildings': {b['b_id']: 24.0 for b in state['buildings']},
        }
