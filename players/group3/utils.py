from core.animal import Animal, Gender
from core.snapshots import HelperSurroundingsSnapshot


def get_animals_in_cell_not_in_ark_and_not_in_my_flock(
    helper_self, snapshot: HelperSurroundingsSnapshot
) -> list[Animal]:
    """Get animals in current cell that we should pick up. Note that since this is for the current cell, we know the genders of all the animals."""
    if helper_self.is_flock_full():
        return []

    # Get current cell coordinates
    cell_x = int(snapshot.position[0])
    cell_y = int(snapshot.position[1])

    # Get current CellView
    if not snapshot.sight.cell_is_in_sight(cell_x, cell_y):
        return []
    cell_view = snapshot.sight.get_cellview_at(cell_x, cell_y)
    cell_animals_all: set[Animal] = cell_view.animals

    # Get animals already on ark
    ark_animals_with_gender: set[tuple[int, Gender]] = set()
    for animal in helper_self.ark_species or []:
        ark_animals_with_gender.add((animal.species_id, animal.gender))

    # Get animals already in our flock
    flock_animals_with_gender: set[tuple[int, Gender]] = set()
    for animal in helper_self.flock:
        flock_animals_with_gender.add((animal.species_id, animal.gender))

    # Find animals worth picking up
    should_obtain = []
    for animal in cell_animals_all:
        if (animal.species_id, animal.gender) in flock_animals_with_gender:
            continue
        if (animal.species_id, animal.gender) in ark_animals_with_gender:
            continue
        should_obtain.append(animal)

    return should_obtain
