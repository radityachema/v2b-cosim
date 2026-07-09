from abc import ABC, abstractmethod


class BaseScheduler(ABC):
    @abstractmethod
    def decide(self, state: dict) -> dict:
        """state: Simulator.get_state() dict ('t','demands','fleet','buildings','network','p_v2b').
        Returns {'fleet': [{'arc','p'}, ...], 'buildings': {b_id: t_sp|None}} -- None means no
        thermal decision, not a fixed setpoint (Building.step() then skips the HVAC relay)."""


class NullScheduler(BaseScheduler):
    def decide(self, state):
        return {
            'fleet': [{'arc': None, 'p': 0.0} for _ in state['fleet']],
            'buildings': {b['b_id']: None for b in state['buildings']},  # None: no decision, not 'do nothing'
        }
