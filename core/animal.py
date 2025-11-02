from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


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
        return Animal(self.species_id, Gender.Unknown if make_unknown else self.gender)
