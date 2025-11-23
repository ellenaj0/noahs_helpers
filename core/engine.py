from random import choice, random
from time import perf_counter

from core.action import Move, Obtain, Release
from core.animal import Animal
from core.ark import Ark
from core.message import Message
from core.player import Player
from core.cell import Cell
from core.player_info import PlayerInfo
from core.sight import Sight
from core.snapshots import HelperSurroundingsSnapshot
from core.timer import Timer
from core.views.player_view import Kind

import core.constants as c


class Engine:
    def __init__(
        self,
        grid: list[list[Cell]],
        ark: Ark,
        helpers: list[Player],
        info_helpers: dict[PlayerInfo, Player],
        time: int,
        animals: dict[Animal, Cell],
        species_stats: dict[int, list[int]],
    ) -> None:
        self.grid = grid
        self.ark = ark
        self.helpers = helpers
        self.info_helpers = info_helpers
        self.time = time
        self.animals: dict[Animal, Cell | PlayerInfo] = dict(animals)
        self.species_stats = species_stats
        self.time_elapsed = 0
        self.last_messages: dict[int, int | None] = {h.id: None for h in self.helpers}

        # record the time used for each turn
        self.times = []

    def _get_sights(self) -> dict[PlayerInfo, list[PlayerInfo]]:
        info_helpers = list(self.info_helpers.keys())
        in_sight: dict[PlayerInfo, list[PlayerInfo]] = {
            helper: [] for helper in info_helpers
        }

        for i in range(len(info_helpers)):
            for j in range(i + 1, len(info_helpers)):
                hi, hj = info_helpers[i], info_helpers[j]

                if hi.distance(hj) <= c.MAX_SIGHT_KM:
                    in_sight[hi].append(hj)
                    in_sight[hj].append(hi)

        return in_sight

    def is_raining(self) -> bool:
        return self.time_elapsed >= self.time - c.START_RAIN

    def run_turn(self) -> float:
        self.last_messages.clear()

        # 1. show helpers their new surroundings:
        # a their position
        # b animals and helpers within 5km sight
        # c turn number
        # d whether it is raining
        # e their flock
        # f if they're in the Ark cell, the current view of the Ark BEFORE unloading any helpers' flock currently in the cell into it.

        # 2. get helpers' one byte message:

        sights = self._get_sights()
        messages_to: dict[PlayerInfo, list[Message]] = {
            helper: [] for helper in self.info_helpers.keys()
        }

        # Tracks the total time consumed by the player
        timer = Timer()

        for hi, helper in self.info_helpers.items():
            sight = Sight((hi.x, hi.y), self.grid)

            helper_ark_view = None
            if hi.is_in_ark():
                helper_ark_view = self.ark.get_view()

            snapshot = HelperSurroundingsSnapshot(
                self.time_elapsed,
                self.is_raining(),
                (hi.x, hi.y),
                sight,
                hi.flock.copy(),
                helper_ark_view,
                timer.copy(),
            )
            last = perf_counter()
            one_byte_message = helper.check_surroundings(snapshot)
            timer.consumed += perf_counter() - last

            if not (0 <= one_byte_message < c.ONE_BYTE):
                raise Exception(
                    f"helper {hi.id} gave incorrect message: {one_byte_message}"
                )

            self.last_messages[hi.id] = one_byte_message

            # broadcast message to all neighbors
            for neighbor in sights[hi]:
                msg = Message(hi.get_view(), one_byte_message)
                messages_to[neighbor].append(msg)

        # 3. broadcast helpers' one byte message to all other helpers in their sight.

        # 4. Let helpers take action on their surroundings:
        # a obtain and/or release animals in their sight
        # b move in any direction

        obtained: dict[Animal, list[PlayerInfo]] = {}
        for hi, helper in self.info_helpers.items():
            last = perf_counter()
            action = helper.get_action(messages_to[hi])
            timer.consumed += perf_counter() - last

            if hi.kind == Kind.Noah and action is not None:
                raise Exception("Noah shouldn't perform an action")

            match action:
                case Release(animal=a):
                    helper_x, helper_y = int(hi.x), int(hi.y)
                    cell = self.grid[helper_y][helper_x]

                    if a not in hi.flock:
                        raise Exception(f"animal {a} not in helper {hi.id}'s flock")

                    hi.flock.remove(a)
                    self.animals[a] = cell
                    cell.animals.add(a)

                case Obtain(animal=a):
                    helper_x, helper_y = int(hi.x), int(hi.y)
                    helper_cell = self.grid[helper_y][helper_x]

                    if len(hi.flock) >= c.MAX_FLOCK_SIZE:
                        raise Exception(
                            f"helper {hi.id} tried to obtain animal with full flock"
                        )

                    match self.animals[a]:
                        case Cell() as cell:
                            if cell != helper_cell or a not in helper_cell.animals:
                                raise Exception(
                                    f"animal {a}, (id={id(a)}) not in helper {hi.id}'s cell {(helper_x, helper_y)}"
                                )

                            if a not in obtained:
                                obtained[a] = []
                            obtained[a].append(hi)

                        case PlayerInfo():
                            # raise Exception(
                            #     f"{hi.get_long_name()} tried obtaining an animal already obtained by {playerinfo.get_long_name()}"
                            # )
                            pass

                case Move(x=x, y=y):
                    if not hi.can_move_to(x, y):
                        raise Exception(
                            f"player cannot move from {hi.x, hi.y} to {(x, y)}"
                        )

                    x_cell, y_cell = int(x), int(y)
                    target_cell = self.grid[y_cell][x_cell]

                    x_curr_cell, y_curr_cell = int(hi.x), int(hi.y)
                    curr_cell = self.grid[y_curr_cell][x_curr_cell]

                    if (x_cell, y_cell) != (x_curr_cell, y_curr_cell):
                        curr_cell.helpers.remove(hi)
                        target_cell.helpers.add(hi)

                    hi.x = x
                    hi.y = y

                    # offload helper's flock to ark
                    if hi.is_in_ark():
                        self.ark.animals = self.ark.animals.union(hi.flock)
                        hi.flock.clear()

        # multiple helpers may try to obtain same animal
        # Only one may actually obtain it.
        # This is decided by:
        # 1. helper with min flock size
        # 2. helper with min id
        for obt_animal, helpers in obtained.items():
            best_helper = min(helpers, key=lambda h: (len(h.flock), h.id))
            helper_x, helper_y = int(best_helper.x), int(best_helper.y)
            helper_cell = self.grid[helper_y][helper_x]

            helper_cell.animals.remove(obt_animal)
            self.animals[obt_animal] = best_helper
            best_helper.flock.add(obt_animal)

        # 5. let free animals move with `ANIMAL_MOVE_PROBABILITY` probability
        for animal, placed in self.animals.items():
            match placed:
                case Cell() as cell:
                    if random() < c.ANIMAL_MOVE_PROBABILITY:
                        neighbor = choice(cell.get_emptiest_neighbors())

                        cell.animals.remove(animal)
                        neighbor.animals.add(animal)
                        # modifying self.animals while iterating
                        # is ok as we're not changing the keys
                        self.animals[animal] = neighbor

        self.time_elapsed += 1
        self.times.append(timer.consumed)
        return timer.consumed

    def get_results(self) -> tuple[int, list[float]]:
        # By the end, all helpers must be in the ark
        if not all([hi.is_in_ark() for hi in self.info_helpers.keys()]):
            return 0, []

        return self.ark.get_score(), self.times

    def run_simulation(self) -> tuple[int, list[float]]:
        while self.time_elapsed < self.time:
            self.run_turn()

        return self.get_results()
