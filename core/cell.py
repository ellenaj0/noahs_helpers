from __future__ import annotations
from random import shuffle

from core.animal import Animal
from core.player_info import PlayerInfo
from core.views.cell_view import CellView


class Cell:
    def __init__(self, x: int, y: int) -> None:
        self.x = x
        self.y = y
        self.animals: set[Animal] = set()
        self.helpers: set[PlayerInfo] = set()

        self.up: Cell | None = None
        self.down: Cell | None = None
        self.left: Cell | None = None
        self.right: Cell | None = None

    def get_view(self, make_unknown: bool) -> CellView:
        free_animals = [a.copy(make_unknown) for a in self.animals]
        shepherded_animals = [
            a.copy(make_unknown) for h in self.helpers for a in h.flock
        ]

        all_animals = free_animals + shepherded_animals
        # ensure readers can't deduce anything from the ordering
        shuffle(all_animals)

        return CellView(
            self.x,
            self.y,
            set(all_animals),
            {h.get_view() for h in self.helpers},
        )

    def get_emptiest_neighbors(self) -> list[Cell]:
        dirs = [
            dir
            for dir in [self.up, self.down, self.left, self.right]
            if dir is not None
        ]

        min_animals = min([len(dir.animals) for dir in dirs])

        return [dir for dir in dirs if len(dir.animals) == min_animals]
