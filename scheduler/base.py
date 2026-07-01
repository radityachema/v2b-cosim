from abc import ABC, abstractmethod


class BaseScheduler(ABC):
    @abstractmethod
    def decide_fleet(self, state: dict) -> list:
        """
        Input:  state from Simulator.get_state()
        Output: [{'arc': (i,j) | None, 'p': float}, ...]  one per vehicle
        """

    @abstractmethod
    def decide_buildings(self, state: dict, p_v2b: dict) -> dict:
        """
        Input:  state from Simulator.get_state(), p_v2b from Simulator.step_fleet()
        Output: {b_id: p_hvac_float}
        """


class NullScheduler(BaseScheduler):
    def decide_fleet(self, state):
        return [{'arc': None, 'p': 0.0} for _ in state['fleet']]

    def decide_buildings(self, state, p_v2b):
        return {b['b_id']: 0.0 for b in state['buildings']}
