from dataclasses import dataclass

from core.views.player_view import PlayerView
import core.constants as c


@dataclass(frozen=True)
class Message:
    from_helper: PlayerView
    contents: int

    def __post_init__(self) -> None:
        if not (0 <= self.contents < (1 << c.ONE_BYTE)):
            raise Exception("message does not fit in one byte")
