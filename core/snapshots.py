from dataclasses import dataclass

from core.animal import Animal
from core.timer import Timer
from core.views.ark_view import ArkView
from core.sight import Sight


@dataclass(frozen=True)
class HelperSurroundingsSnapshot:
    time_elapsed: int
    is_raining: bool
    position: tuple[float, float]
    sight: Sight
    flock: set[Animal]
    ark_view: ArkView | None
    timer: Timer
