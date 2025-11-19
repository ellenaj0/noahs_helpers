from random import choice, randint

from core.action import Action, Move, Obtain
from core.message import Message
from core.player import Player
from core.snapshots import HelperSurroundingsSnapshot
from core.views.player_view import Kind
from core.views.cell_view import CellView


def distance(x1: float, y1: float, x2: float, y2: float) -> float:
    return (abs(x1 - x2) ** 2 + abs(y1 - y2) ** 2) ** 0.5


class SearchAndRescue(Player):
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
        print(f"I am {self}")

        self.is_raining = False
        self.hellos_received = []
        self.mode = "waiting"
        self.direction = (0, 0)
        self.internal_ark = set()
        self.countdown = 0

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
                for animal in cellview.animals:
                    dist = distance(*self.position, cellview.x, cellview.y)
                    if (animal.species_id, animal.gender) not in self.internal_ark:
                        if closest_animal is None:
                            closest_animal = animal
                            closest_dist = dist
                            closest_pos = (cellview.x, cellview.y)
                        elif dist < closest_dist:
                            closest_animal = choice(tuple(cellview.animals))
                            closest_dist = dist
                            closest_pos = (cellview.x, cellview.y)

        return closest_pos

    def _get_random_location(self) -> tuple[float, float]:
        old_x, old_y = self.position
        count = 0
        while True:
            count += 1
            dx, dy = randint(0, 1000), randint(0, 1000)
            # print(dx, dy, count)
            # input()
            if distance(dx, dy, self.ark_position[0], self.ark_position[0]) < 1000:
                break

        return dx, dy

    def check_surroundings(self, snapshot: HelperSurroundingsSnapshot) -> int:
        # I can't trust that my internal position and flock matches the simulators
        # For example, I wanted to move in a way that I couldn't
        # or the animal I wanted to obtain was actually obtained by another helper
        self.position = snapshot.position
        self.flock = snapshot.flock

        self.sight = snapshot.sight
        self.is_raining = snapshot.is_raining

        if snapshot.ark_view is not None:
            arc_animals = set()
            for animal in snapshot.ark_view.animals:
                id_number, gender = animal.species_id, animal.gender
                arc_animals.add((id_number, gender))
            # print(snapshot.ark_view.animals)
            self.internal_ark = arc_animals

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
        # print(self.internal_ark)
        for msg in messages:
            if 1 << (msg.from_helper.id % 8) == msg.contents:
                self.hellos_received.append(msg.contents)

        # noah shouldn't do anything
        if self.kind == Kind.Noah:
            return None

        # If it's raining, go to ark
        if self.is_raining:
            return Move(*self.move_towards(*self.ark_position))

        # If I have obtained an animal, go to ark
        if not self.is_flock_empty():
            return Move(*self.move_towards(*self.ark_position))

        if self.mode == "move_away":
            if self.countdown <= 0:
                self.mode = "waiting"
            else:
                self.countdown -= 1
                return Move(*self.move_towards(*self.direction))

        # If I've reached an animal, I'll obtain it
        cellview = self._get_my_cell()
        if len(cellview.animals) > 0:
            for animal in cellview.animals:
                if (animal.species_id, animal.gender) not in self.internal_ark:
                    # # This means the random_player will even attempt to
                    # # (unsuccessfully) obtain animals in other helpers' flocks
                    # random_animal = choice(tuple(cellview.animals))
                    return Obtain(animal)
            direction = self._get_random_location()
            self.mode = "move_away"
            self.direction = direction
            self.countdown = 10
            return Move(*self.move_towards(*self.direction))

        # If I see any animals, I'll chase the closest one
        closest_animal = self._find_closest_animal()
        if closest_animal:
            # This means the random_player will even approach
            # animals in other helpers' flocks
            return Move(*self.move_towards(*closest_animal))

        # Move in a random direction
        if self.mode == "waiting":
            direction = self._get_random_location()
            self.mode = "moving"
            self.direction = direction
            return Move(*self.move_towards(*self.direction))

        else:
            if self.position == self.direction or self.position == self.ark_position:
                direction = self._get_random_location()
                self.mode = "moving"
                self.direction = direction
                return Move(*self.move_towards(*self.direction))
            else:
                return Move(*self.move_towards(*self.direction))
