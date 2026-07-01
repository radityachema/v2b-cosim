from abc import ABC, abstractmethod


class BaseScheduler(ABC):
    @abstractmethod
    def decide(self, state: dict) -> dict:
        """
        Input:  state from Simulator.get_state()
        Output: {
            'fleet':     [{'arc': (i,j) | None, 'p': float}, ...],  # one per vehicle
            'buildings': {b_id: {'p_hvac': float}}
        }
        """


class NullScheduler(BaseScheduler):
    def decide(self, state):
        return {
            'fleet': [{'arc': None, 'p': 0.0} for _ in state['fleet']],
            'buildings': {b['b_id']: {'p_hvac': 0.0} for b in state['buildings']},
        }
