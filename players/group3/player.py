import math
from random import choice, random
from core.animal import Animal
from core.message import Message
from core.player import Player
from core.snapshots import HelperSurroundingsSnapshot
from core.views.cell_view import CellView
from core.views.player_view import Kind
from core.action import Action, Move, Obtain
import core.constants as c


def distance(x1: float, y1: float, x2: float, y2: float) -> float:
    return (abs(x1 - x2) ** 2 + abs(y1 - y2) ** 2) ** 0.5


class Player3(Player):
    def __init__(
        self,
        id: int,
        ark_x: int,
        ark_y: int,
        kind: Kind,
        num_helpers: int,
        species_populations: dict[str, int],
    ):
        super().__init__(id, ark_x, ark_y, kind, num_helpers, species_populations)
        self.ark_species: set[Animal] = set()
        self.is_raining = False
        self.hellos_received = []
        self.angle = math.radians(random() * 360)

    def check_surroundings(self, snapshot: HelperSurroundingsSnapshot) -> int:
        self.position = snapshot.position
        self.flock = snapshot.flock
        if snapshot.ark_view:
            self.ark_species.update(snapshot.flock)

        self.sight = snapshot.sight
        self.is_raining = snapshot.is_raining

        # if I didn't receive any messages, broadcast "hello"
        # a "hello" message is when a player's id bit is set
        if len(self.hellos_received) == 0:
            msg = 1 << (self.id % 8)
        else:
            # else, acknowledge all "hello"'s I got last turn
            # do this with a bitwise OR of all IDs I got
            msg = 0
            for hello in self.hellos_received:
                msg |= hello
            self.hellos_received = []

        if not self.is_message_valid(msg):
            msg = msg & 0xFF

        return msg

    def get_action(self, messages: list[Message]) -> Action | None:
        for msg in messages:
            if 1 << (msg.from_helper.id % 8) == msg.contents:
                self.hellos_received.append(msg.contents)
        # noah shouldn't do anything
        if self.kind == Kind.Noah:
            return None

        # If it's raining, go to ark
        if self.is_raining:
            return Move(*self.move_towards(*self.ark_position))

        # if self.is_flock_full():
        #     return Move(*self.move_towards(*self.ark_position))

        # If I have obtained an animal, go to ark
        if not self.is_flock_empty():
            return Move(*self.move_towards(*self.ark_position))

        # If I've reached an animal, I'll obtain it
        """ cellview = self._get_my_cell()
        if len(cellview.animals) > 0:
            # This means the random_player will even attempt to
            # (unsuccessfully) obtain animals in other helpers' flocks
            random_animal = choice(tuple(cellview.animals))
            return Obtain(random_animal) """

        # don't move too far from the ark
        if distance(*self.position, self.ark_position[0], self.ark_position[1]) >= 1007:
            self.angle = math.radians(random() * 360)
            print("distance too far")
            return Move(*self.move_towards(*self.ark_position))

        cellview = self._get_my_cell()
        cellview.animals
        # grab an animal that does not appear to be in flock or in the ark
        if len(cellview.animals) > 0:
            for animal in cellview.animals:
                if animal not in self.ark_species and animal not in self.flock:
                    print("obtained")
                    return Obtain(animal)

        # If I see any animals, I'll chase the closest one
        closest_animal = self._find_closest_animal()
        if closest_animal:
            dist_animal = distance(*self.position, *closest_animal)
            if dist_animal > 0.01 and dist_animal <= 3:
                print("move towards animal")
                # This means the random_player will even approach
                # animals in other helpers' flocks
                return Move(*self.move_towards(*closest_animal))

        return Move(*self.move_dir())

    def get_distance(self, from_x, from_y, to_x, to_y):
        print(math.sqrt((to_x - from_x) ** 2 + (to_y - from_y) ** 2))
        return math.sqrt((to_x - from_x) ** 2 + (to_y - from_y) ** 2)

    def _get_my_cell(self) -> CellView:
        xcell, ycell = tuple(map(int, self.position))
        if not self.sight.cell_is_in_sight(xcell, ycell):
            raise Exception(f"{self} failed to find own cell")

        return self.sight.get_cellview_at(xcell, ycell)

    def _find_closest_animal(self) -> tuple[int, int] | None:
        closest_animal = None
        closest_dist = -1
        closest_pos = None
        for cellview in self.sight:
            if len(cellview.animals) > 0:
                dist = distance(*self.position, cellview.x, cellview.y)
                if closest_animal is None or dist < closest_dist:
                    closest_animal = choice(tuple(cellview.animals))
                    closest_dist = dist
                    closest_pos = (cellview.x, cellview.y)

        return closest_pos

    def move_dir(self) -> tuple[float, float]:
        step_size = c.MAX_DISTANCE_KM * 0.99
        x0, y0 = self.position
        x1, y1 = (
            x0 + step_size * math.cos(self.angle),
            y0 + step_size * math.sin(self.angle),
        )
        if self.can_move_to(x1, y1):
            # print(x1, y1)
            return x1, y1
        print("move away")
        self.angle = math.radians(random() * 360)
        return x0, y0
