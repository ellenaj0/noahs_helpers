from __future__ import annotations
import pygame
from dataclasses import dataclass
from enum import Enum

import core.constants as c


class Gender(Enum):
    Male = 0
    Female = 1
    Unknown = 2


# `eq=False` cause we can have multiple
# animals of the same species and gender
@dataclass(frozen=True, eq=False)
class Animal:
    species_id: int
    gender: Gender

    def copy(self, make_unknown: bool) -> Animal:
        if not make_unknown:
            return self

        return Animal(self.species_id, Gender.Unknown)

    def _id_to_letter(self) -> str:
        return chr(self.species_id + ord("a"))

    def _gender_to_color(self) -> tuple[int, int, int]:
        match self.gender:
            case Gender.Female:
                return c.FEMALE_ANIMAL_COLOR
            case Gender.Male:
                return c.MALE_ANIMAL_COLOR

        raise Exception(f"can't turn gender {self.gender} to color")

    def draw(
        self, screen: pygame.Surface, font: pygame.font.Font, pos: tuple[int, int]
    ):
        text = font.render(self._id_to_letter(), False, self._gender_to_color())
        rect = text.get_rect(center=pos)
        screen.blit(text, rect)

    def draw_on_map(self, screen: pygame.Surface, pos: tuple[int, int]):
        pygame.draw.circle(screen, self._gender_to_color(), pos, 2)
