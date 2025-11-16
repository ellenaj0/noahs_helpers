from __future__ import annotations
import pygame
from typing import final

from core.animal import Animal
from core.ui.utils import write_at
from core.views.player_view import Kind, PlayerView

import core.constants as c


class PlayerInfo:
    def __init__(
        self,
        id: int,
        x: float,
        y: float,
        ark_position: tuple[float, float],
        kind: Kind,
        flock: set[Animal],
    ) -> None:
        self.id = id
        self.x = x
        self.y = y
        self.ark_position = ark_position
        self.kind = kind
        self.flock = flock

    @final
    def distance(self, other: PlayerInfo) -> float:
        # this is not inherently bad, but just might
        # be an indicator that our calling logic is bad
        if self.id == other.id:
            raise Exception(f"{self}: Calculating distance with myself?")

        x1, y1 = self.x, self.y
        x2, y2 = other.x, other.y

        # pytharogas
        return (abs(x2 - x1) ** 2 + abs(y2 - y1) ** 2) ** 0.5

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

    @final
    def get_view(self) -> PlayerView:
        return PlayerView(self.id, self.kind)

    @final
    def is_in_ark(self) -> bool:
        return (
            abs(self.x - self.ark_position[0]) <= c.EPS
            and abs(self.y - self.ark_position[1]) <= c.EPS
        )

    @final
    def draw(
        self, screen: pygame.Surface, font: pygame.font.Font, pos: tuple[int, int]
    ):
        text = font.render(self.get_short_name(), True, c.HELPER_COLOR)
        rect = text.get_rect(center=pos)
        screen.blit(text, rect)

    @final
    def draw_on_map(self, screen: pygame.Surface, pos: tuple[int, int]):
        pygame.draw.circle(screen, c.HELPER_COLOR, pos, 4)

    @final
    def draw_flock(
        self, screen: pygame.Surface, font: pygame.font.Font, start_pos: tuple[int, int]
    ):
        if self.kind == Kind.Noah:
            raise Exception("Noah doesn't have a flock")

        x, y = start_pos
        flist = list(self.flock) + [None] * (c.MAX_FLOCK_SIZE - len(self.flock))
        for i in range(c.MAX_FLOCK_SIZE):
            fi = flist[i]
            pos = (x, y)

            if fi is None:
                write_at(screen, font, "_", pos)
            else:
                fi.draw(screen, font, pos)

            x += 40

    @final
    def draw_message(
        self,
        screen: pygame.Surface,
        font: pygame.font.Font,
        start_pos: tuple[int, int],
        msg: int,
    ):
        write_at(
            screen,
            font,
            f"msg 0b{msg:08b}={msg}",
            start_pos,
            align="left",
        )

    @final
    def can_move_to(self, x: float, y: float) -> bool:
        # noah is stuck on the ark
        if self.kind == Kind.Noah:
            return False

        if not (0 <= x < c.X and 0 <= y < c.Y):
            return False

        return (abs(self.x - x) ** 2 + abs(self.y - y) ** 2) * 0.5 <= c.MAX_DISTANCE_KM
