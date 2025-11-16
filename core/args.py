from __future__ import annotations
from dataclasses import dataclass
import json
import pathlib

from core.player import Player
import core.constants as c

from players.group1.player import Player1
from players.group10.player import Player10
from players.group2.player import Player2
from players.group3.player import Player3
from players.group4.player import Player4
from players.group5.player import Player5
from players.group6.player import Player6
from players.group7.player import Player7
from players.group8.player import Player8
from players.group9.player import Player9
from players.random_player import RandomPlayer

PLAYERS = {
    "r": RandomPlayer,
    "1": Player1,
    "2": Player2,
    "3": Player3,
    "4": Player4,
    "5": Player5,
    "6": Player6,
    "7": Player7,
    "8": Player8,
    "9": Player9,
    "10": Player10,
}


@dataclass
class Args:
    gui: bool
    seed: int
    player: type[Player]
    num_helpers: int
    animals: list[int]
    time: int
    ark: tuple[int, int]


@dataclass
class MapArgs:
    num_helpers: int
    animals: list[int]
    ark: tuple[int, int]

    @staticmethod
    def read(path: pathlib.Path) -> MapArgs:
        data = None
        with open(path, "r") as file:
            data = json.load(file)

        num_helpers = data.get("num_helpers")
        if not isinstance(num_helpers, int) or num_helpers <= 1:
            raise TypeError("'num_helpers' must be >= 2")

        animals = data.get("animals")
        if not isinstance(animals, list) or not all(
            isinstance(a, int) for a in animals
        ):
            raise TypeError("'animals' must be a list of ints")
        if any(a < 2 for a in animals):
            raise ValueError("each value in 'animals' must be >= 2")

        ark_pos = data.get("ark")
        if (
            not isinstance(ark_pos, (list, tuple))
            or len(ark_pos) != 2
            or not all(isinstance(v, int) for v in ark_pos)
        ):
            raise TypeError("'ark_position' must be an X,Y pair")

        if not (0 <= ark_pos[0] < c.X and 0 <= ark_pos[1] < c.Y):
            raise ValueError(f"'ark_position' coordinate must be between 0 and {c.Y}")
        ark = (ark_pos[0], ark_pos[1])

        return MapArgs(num_helpers, animals, ark)
