from core.animal import Animal, Gender
from core.views.ark_view import ArkView
import core.constants as c


class Ark:
    def __init__(
        self,
        position: tuple[int, int],
        species_stats: dict[int, list[int]],
    ) -> None:
        self.position = position
        self.animals: set[Animal] = set()
        self.species_stats = species_stats

    def get_view(self) -> ArkView:
        return ArkView(self.position, self.animals.copy())

    def get_score(self) -> float:
        species = self.get_species()
        score = 0

        for has_male, has_female in species.values():
            if has_male and has_female:
                score += c.SCORE_FOR_BOTH_GENDERS_SAVED

            elif has_male or has_female:
                score += c.SCORE_FOR_EITHER_GENDER_SAVED

        return score

    def get_species(self) -> dict[int, list[bool]]:
        species_in_ark: dict[int, list[bool]] = {
            sid: [False, False] for sid in self.species_stats.keys()
        }

        for animal in self.animals:
            sid = animal.species_id
            if animal.gender == Gender.Male:
                species_in_ark[sid][0] = True
            elif animal.gender == Gender.Female:
                species_in_ark[sid][1] = True

        return species_in_ark
