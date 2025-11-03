from random import choice, random

from core.action import Move, Obtain, Release
from core.animal import Animal
from core.ark import Ark
from core.message import Message
from core.player import Player
from core.cell import Cell
from core.sight import Sight
from core.snapshots import HelperSurroundingsSnapshot

import core.constants as c


class Engine:
    def __init__(
        self,
        grid: list[list[Cell]],
        ark: Ark,
        helpers: list[Player],
        time: int,
        animals: dict[Animal, Cell],
    ) -> None:
        self.grid = grid
        self.ark = ark
        self.helpers = helpers
        self.time = time
        self.free_animals = animals
        self.time_elapsed = 0

    def _get_sights(self) -> dict[Player, list[Player]]:
        in_sight: dict[Player, list[Player]] = {helper: [] for helper in self.helpers}

        for i, helper in enumerate(self.helpers):
            for j in range(i + 1, len(self.helpers)):
                neighbor = self.helpers[j]
                if helper.distance(neighbor) <= c.MAX_SIGHT_KM:
                    in_sight[helper].append(neighbor)
                    in_sight[neighbor].append(helper)

        return in_sight

    def is_raining(self) -> bool:
        return self.time_elapsed >= self.time - c.START_RAIN

    def run_turn(self) -> None:
        is_raining = self.is_raining()
        ark_view = self.ark.get_view()

        # 1. show helpers their new surroundings:
        # a their position
        # b animals and helpers within 5km sight
        # c turn number
        # d whether it is raining
        # e their flock
        # f if they're in the Ark cell, the current view of the Ark BEFORE unloading any helpers' flock currently in the cell into it.

        # 2. get helpers' one byte message:

        sights = self._get_sights()
        messages_to: dict[Player, list[Message]] = {
            helper: [] for helper in self.helpers
        }

        for helper in self.helpers:
            sight = Sight(helper.position, self.grid)

            helper_ark_view = None
            if helper.is_in_ark():
                helper_ark_view = ark_view

            snapshot = HelperSurroundingsSnapshot(
                self.time_elapsed, is_raining, helper.position, sight, helper_ark_view
            )
            one_byte_message = helper.check_surroundings(snapshot)
            if not (0 <= one_byte_message < c.ONE_BYTE):
                raise Exception(
                    f"helper {helper.id} gave incorrect message: {one_byte_message}"
                )

            # broadcast message to all neighbors
            for neighbor in sights[helper]:
                msg = Message(helper.get_view(), one_byte_message)
                messages_to[neighbor].append(msg)

        # 3. broadcast helpers' one byte message to all other helpers in their sight.

        # 4. Let helpers take action on their surroundings:
        # a obtain and/or release animals in their sight
        # b move in any direction

        for helper in self.helpers:
            action = helper.get_action(messages_to[helper])

            match action:
                case Release(animal=a):
                    print(f"{helper.id}: relasing {a}")
                    helper_x, helper_y = tuple(map(int, helper.position))
                    cell = self.grid[helper_y][helper_x]

                    if a not in helper.flock:
                        raise Exception(f"animal {a} not in helper {helper.id}'s flock")

                    helper.flock.remove(a)
                    self.free_animals[a] = cell

                case Obtain(animal=a):
                    print(f"{helper.id}: obtaining {a}")

                    helper_x, helper_y = tuple(map(int, helper.position))
                    helper_cell = self.grid[helper_y][helper_x]

                    if len(helper.flock) >= c.MAX_FLOCK_SIZE:
                        raise Exception(
                            f"helper {helper.id} tried to obtain animal with full flock"
                        )

                    if a not in helper_cell.animals:
                        raise Exception(
                            f"animal {a} not in helper {helper.id}'s cell {(helper_x, helper_y)}"
                        )

                    helper_cell.animals.remove(a)
                    del self.free_animals[a]
                    helper.flock.add(a)

                case Move(x=x, y=y):
                    print(f"{helper.id}: moving to {(x, y)}")

                    if not helper.can_move_to(x, y):
                        raise Exception(
                            f"player cannot move from {helper.position} to {(x, y)}"
                        )

                    helper.position = (x, y)

        # 5. let free animals move with `ANIMAL_MOVE_PROBABILITY` probability
        for animal, cell in self.free_animals.items():
            if random() < c.ANIMAL_MOVE_PROBABILITY:
                neighbor = choice(cell.get_emptiest_neighbors())

                print(f"{animal} moved: {cell.x, cell.y} -> {neighbor.x, neighbor.y}")

                cell.animals.remove(animal)
                neighbor.animals.add(animal)
                # this is ok as we're not changing the keys
                self.free_animals[animal] = neighbor

        self.time_elapsed += 1

    def run_simulation(self) -> None:
        while self.time_elapsed < self.time:
            self.run_turn()
