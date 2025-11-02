from __future__ import annotations
from abc import ABC, abstractmethod
from typing import final

from core.action import Action
from core.animal import Animal
from core.message import Message
from core.views.player_view import PlayerView
from core.snapshots import HelperSurroundingsSnapshot

import core.constants as c


class Player(ABC):
    def __init__(self, id: int, ark_x: int, ark_y: int):
        self.id = id
        self.ark_position = (ark_x, ark_y)
        self.position = (float(ark_x), float(ark_y))
        self.flock: list[Animal] = []

    def __str__(self) -> str:
        return f"{self.__module__}(id={self.id})"

    def __repr__(self) -> str:
        return str(self)

    @final
    def distance(self, other: Player) -> float:
        # this is not inherently bad, but just might
        # be an indicator that our calling logic is bad
        if self.id == other.id:
            raise Exception(f"{self}: Calculating distance with myself?")

        x1, y1 = self.position
        x2, y2 = other.position

        # pytharogas
        return (abs(x2 - x1) ** 2 + abs(y2 - y1) ** 2) ** 0.5

    @final
    def get_view(self) -> PlayerView:
        return PlayerView(self.id)

    @final
    def is_in_ark(self) -> bool:
        return (
            int(self.position[0]) == self.ark_position[0]
            and int(self.position[1]) == self.ark_position[1]
        )

    @final
    def is_message_valid(self, msg: int) -> bool:
        return 0 <= msg < (1 << c.ONE_BYTE)

    @final
    def can_move_to(self, x: float, y: float) -> bool:
        curr_x, curr_y = self.position

        return (abs(curr_x - x) ** 2 + abs(curr_y - y) ** 2) * 0.5 <= 1

    @abstractmethod
    def check_surroundings(self, snapshot: HelperSurroundingsSnapshot) -> int:
        raise Exception("not implemented")

    @abstractmethod
    def get_action(self, messages: list[Message]) -> Action:
        raise Exception("not implemented")
