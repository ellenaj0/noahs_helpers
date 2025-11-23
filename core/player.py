from __future__ import annotations
from abc import ABC, abstractmethod
from typing import final
from math import hypot


from core.action import Action
from core.animal import Animal
from core.message import Message
from core.player_info import PlayerInfo
from core.snapshots import HelperSurroundingsSnapshot
from core.views.player_view import Kind

import core.constants as c


class Player(ABC):
    def __init__(
        self,
        id: int,
        ark_x: int,
        ark_y: int,
        kind: Kind,
        num_helpers: int,
        species_populations: dict[str, int],
    ):
        self.kind = kind
        self.id = id
        self.ark_position = (ark_x, ark_y)
        self.position = (float(ark_x), float(ark_y))
        self.flock: set[Animal] = set()
        self.num_helpers = num_helpers
        self.species_populations = species_populations

    def __str__(self) -> str:
        return self.__class__.__name__

    def __repr__(self) -> str:
        return str(self)

    @final
    def get_info(self) -> PlayerInfo:
        return PlayerInfo(
            self.id,
            self.position[0],
            self.position[1],
            self.ark_position,
            self.kind,
            self.flock,
        )

    @final
    def is_in_ark(self) -> bool:
        return (
            abs(self.position[0] - self.ark_position[0]) <= c.EPS
            and abs(self.position[1] - self.ark_position[1]) <= c.EPS
        )

    @final
    def is_message_valid(self, msg: int) -> bool:
        return 0 <= msg < c.ONE_BYTE

    @final
    def can_move_to(self, x: float, y: float) -> bool:
        # noah is stuck on the ark
        if self.kind == Kind.Noah:
            return False

        if not (0 <= x < c.X and 0 <= y < c.Y):
            return False

        curr_x, curr_y = self.position
        return (abs(curr_x - x) ** 2 + abs(curr_y - y) ** 2) * 0.5 <= c.MAX_DISTANCE_KM

    @final
    def is_flock_full(self) -> bool:
        return len(self.flock) == c.MAX_FLOCK_SIZE

    @final
    def is_flock_empty(self) -> bool:
        return len(self.flock) == 0

    @final
    def move_towards(self, x: float, y: float) -> tuple[float, float]:
        # let's be conservative, we don't want to move too far
        step_size = c.MAX_DISTANCE_KM * 0.99

        cx, cy = self.position

        dx = x - cx
        dy = y - cy
        dist = hypot(dx, dy)

        if dist == 0:
            return cx, cy

        if dist <= step_size:
            return cx + dx, cy + dy

        scale = step_size / dist

        return cx + dx * scale, cy + dy * scale

    @final
    def get_long_name(self) -> str:
        return (
            self.kind.name if self.kind == Kind.Noah else f"{self.kind.name} {self.id}"
        )

    @final
    def get_short_name(self) -> str:
        return (
            self.kind.value if self.kind == Kind.Noah else f"{self.kind.value}{self.id}"
        )

    @abstractmethod
    def check_surroundings(self, snapshot: HelperSurroundingsSnapshot) -> int:
        raise Exception("not implemented")

    @abstractmethod
    def get_action(self, messages: list[Message]) -> Action | None:
        raise Exception("not implemented")
