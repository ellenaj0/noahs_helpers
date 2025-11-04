import random

from core.animal import Gender, Animal
from core.ark import Ark
from core.engine import Engine
from core.player import Player
from core.ui.ark_ui import ArkUI
from core.cell import Cell

import core.constants as c


class ArkRunner:
    def __init__(
        self,
        player_class: type[Player],
        num_helpers: int,
        animals: list[int],
        time: int,
        ark_pos: tuple[int, int],
    ):
        self.player_class = player_class
        self.num_helpers = num_helpers
        self.animals = animals
        self.time = time
        self.ark_pos = ark_pos

    def setup_engine(self) -> Engine:
        self.grid = [[Cell(x, y) for x in range(c.X)] for y in range(c.Y)]

        # link neighbouring cells
        for y in range(c.Y):
            for x in range(c.X):
                cell = self.grid[y][x]
                # if y < c.Y - 1:
                #     cell.down = self.grid[y + 1][x]
                # if x < c.X - 1:
                #     cell.right = self.grid[y][x + 1]
                if y > 0:
                    cell.up = self.grid[y - 1][x]
                    cell.up.down = cell
                if x > 0:
                    cell.left = self.grid[y][x - 1]
                    cell.left.right = cell

        # generate animals in landscape
        animals: dict[Animal, Cell] = {}
        species_stats: dict[int, list[int]] = {}

        for species_id, count in enumerate(self.animals):
            first_male = Animal(species_id, Gender.Male)
            first_female = Animal(species_id, Gender.Female)
            group = [first_male, first_female]

            species_stats[species_id] = [1, 1]

            for _ in range(count - 2):
                if random.random() < 0.5:
                    group.append(Animal(species_id, Gender.Male))
                    species_stats[species_id][0] += 1
                else:
                    group.append(Animal(species_id, Gender.Female))
                    species_stats[species_id][1] += 1

            # place animals in random cells
            for animal in group:
                x, y = random.randint(0, c.X - 1), random.randint(0, c.Y - 1)
                cell = self.grid[y][x]
                cell.animals.add(animal)
                animals[animal] = cell

        self.ark = Ark(self.ark_pos)

        self.helpers = [
            self.player_class(id, *self.ark.position) for id in range(self.num_helpers)
        ]

        engine = Engine(
            self.grid, self.ark, self.helpers, self.time, animals, species_stats
        )

        return engine

    def run(self) -> dict:
        engine = self.setup_engine()
        engine.run_simulation()

        return {}

    def run_gui(self):
        engine = self.setup_engine()
        visualizer = ArkUI(engine)
        visualizer.run()
