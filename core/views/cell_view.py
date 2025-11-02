from __future__ import annotations
from dataclasses import dataclass

from core.animal import Animal
from core.views.player_view import PlayerView


@dataclass(frozen=True)
class CellView:
    x: int
    y: int
    animals: set[Animal]
    helpers: set[PlayerView]
