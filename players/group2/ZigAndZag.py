from random import choice, randint

from core.action import Action, Move, Obtain
from core.message import Message
from core.player import Player
from core.snapshots import HelperSurroundingsSnapshot
from core.views.player_view import Kind
from core.views.cell_view import CellView
from core.animal import Gender


def distance(x1: float, y1: float, x2: float, y2: float) -> float:
    return (abs(x1 - x2) ** 2 + abs(y1 - y2) ** 2) ** 0.5


class Player2(Player):
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
        self.complete_species = set()

        self.countdown = 0
        self.rain = False
        self.timer = 1008

        self.recent_positions = []  # Track last 50 positions
        self.max_history = 50

        # Grid-based exploration
        # Scale down grid map into 100x100 cells (10x10 grid)
        self.grid_size = 100
        self.visited_cells = set()
        self.current_target_cell = None

        # Zigzag path variable
        self.zigzag_path = None

        self.clock = 0

    def _get_my_cell(self) -> CellView:
        xcell, ycell = tuple(map(int, self.position))
        if not self.sight.cell_is_in_sight(xcell, ycell):
            raise Exception(f"{self} failed to find own cell")

        return self.sight.get_cellview_at(xcell, ycell)

    def _get_next_grid_target(self) -> tuple[float, float]:
        """Pick the next unvisited grid cell to explore"""
        # Try to find an unvisited cell
        # NOTE: can tune later this was arbitrarily picked for now
        attempts = 0
        max_attempts = 100

        while attempts < max_attempts:
            # Pick a random grid cell
            grid_x = randint(0, 9)
            grid_y = randint(0, 9)

            if (grid_x, grid_y) not in self.visited_cells:
                self.visited_cells.add((grid_x, grid_y))
                self.current_target_cell = (grid_x, grid_y)
                return self._get_grid_center(grid_x, grid_y)

            attempts += 1

        # If most cells are visited then it's fine and we'll reset to allow revists
        self.visited_cells.clear()
        grid_x = randint(0, 9)
        grid_y = randint(0, 9)
        self.visited_cells.add((grid_x, grid_y))
        self.current_target_cell = (grid_x, grid_y)
        return self._get_grid_center(grid_x, grid_y)

    def _get_grid_cell(self, x: float, y: float) -> tuple[int, int]:
        """Convert a position to the scaled down 10x10 grid cell coordinates"""
        grid_x = int(x // self.grid_size)
        grid_y = int(y // self.grid_size)
        return (grid_x, grid_y)

    def _get_grid_center(self, grid_x: int, grid_y: int) -> tuple[float, float]:
        """Get the center point of the scaled down 10x10 grid cell"""
        center_x = grid_x * self.grid_size + self.grid_size // 2
        center_y = grid_y * self.grid_size + self.grid_size // 2
        return (center_x, center_y)

    def animal_to_tuple(self, animal):
        s_id = animal.species_id
        if animal.gender == Gender.Male:
            g = 0
        elif animal.gender == Gender.Female:
            g = 1
        else:
            g = 2
        return (s_id, g)

    def _find_closest_animal(self) -> tuple[int, int] | None:
        closest_animal = None
        closest_dist = -1
        closest_pos = None
        for cellview in self.sight:
            if len(cellview.animals) > 0:
                for animal in cellview.animals:
                    dist = distance(*self.position, cellview.x, cellview.y)
                    if (
                        (animal.species_id, animal.gender) not in self.internal_ark
                        and animal.species_id not in self.complete_species
                    ):
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
            dx, dy = randint(0, 999), randint(0, 999)
            # print(dx, dy, count)
            # input()
            if distance(dx, dy, self.ark_position[0], self.ark_position[1]) < 1000:
                break

        return dx, dy

    def make_zigzag_path(self, start, end, steps=10, amplitude=40):
        sx, sy = start
        tx, ty = end

        path = []

        dx = tx - sx
        dy = ty - sy
        length = (dx**2 + dy**2) ** 0.5 or 1
        dx /= length
        dy /= length

        # perpendicular vector
        px = -dy
        py = dx

        # boundaries
        xmin, xmax = 0, 999
        ymin, ymax = 0, 999

        def clamp(v, lo, hi):
            return max(lo, min(v, hi))

        for i in range(steps + 1):
            t = i / steps

            # point along line
            lx = sx + (tx - sx) * t
            ly = sy + (ty - sy) * t

            # zig (even) or zag (odd)
            offset = amplitude if i % 2 else -amplitude

            zx = lx + px * offset
            zy = ly + py * offset

            # clamp inside bounding box
            zx = clamp(zx, xmin, xmax)
            zy = clamp(zy, ymin, ymax)

            path.append((zx, zy))

        # final endpoint
        path.append(end)

        return path

    def check_surroundings(self, snapshot: HelperSurroundingsSnapshot) -> int:
        # I can't trust that my internal position and flock matches the simulators
        # For example, I wanted to move in a way that I couldn't
        # or the animal I wanted to obtain was actually obtained by another helper
        self.position = snapshot.position
        self.flock = snapshot.flock

        self.sight = snapshot.sight
        self.is_raining = snapshot.is_raining

        # Mark current grid cell(the scaled down 10x10 one that hosts 10 cells) as visited when exploring
        if self.is_flock_empty():
            current_grid = self._get_grid_cell(*self.position)
            self.visited_cells.add(current_grid)

        # Track when we're exploring (not when returning to ark with animals)
        if self.is_flock_empty() or len(self.recent_positions) == 0:
            self.recent_positions.append(self.position)
            # Keep only the most recent positions
            if len(self.recent_positions) > self.max_history:
                self.recent_positions.pop(0)

        # Clear some history when at ark to allow fresh exploration cycles(last 20 for now)
        if snapshot.ark_view is not None and self.is_flock_empty():
            # NOTE: tune later
            if len(self.recent_positions) > 20:
                self.recent_positions = self.recent_positions[-20:]

        """Update internal arc information"""
        if snapshot.ark_view is not None:
            arc_animals = set()
            for animal in snapshot.ark_view.animals:
                arc_animals.add(self.animal_to_tuple(animal))
            self.internal_ark = arc_animals
            for tuple in arc_animals:
                s_id = tuple[0]
                if (s_id, 0) in arc_animals and (s_id, 1) in arc_animals:
                    self.complete_species.add(s_id)

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
        self.clock += 1
        # print(self.mode)
        # print(self.internal_ark)
        for msg in messages:
            if 1 << (msg.from_helper.id % 8) == msg.contents:
                self.hellos_received.append(msg.contents)

        # noah shouldn't do anything
        if self.kind == Kind.Noah:
            return None

        # Get your ass back to the ark now
        if self.mode == "get_back":
            return Move(*self.move_towards(*self.ark_position))

        """If it's raining, keep searching. However, if you are too close to 
        the deadline, set mode to get_back to immediatly travel to the arc"""
        if self.rain:
            self.timer -= 1
            if (
                self.timer
                - distance(
                    self.position[0],
                    self.position[1],
                    self.ark_position[0],
                    self.ark_position[1],
                )
                <= 20
            ):
                self.mode = "get_back"

        if self.is_raining and not self.rain:
            self.rain = True

        # If I have obtained 3 animals, zig zag back
        if len(self.flock) == 3:
            # CLEAR zigzag path so we don't continue it later
            self.zigzag_path = None
            self.current_target_cell = None

            # Now heading to ark, straight back
            self.direction = self.ark_position
            return Move(*self.move_towards(*self.ark_position))

        """If a helper checked and animal and noted it is already in the arc
        we use this function to force a 10 move walk"""
        print(f"coundown: {self.countdown}")
        if self.mode == "move_away":
            if self.countdown <= 0:
                self.mode = "moving"
            else:
                self.countdown -= 1
                return Move(*self.move_towards(*self.direction))

        # If I've reached an animal, I'll obtain it
        cellview = self._get_my_cell()
        print(cellview.animals)
        if len(cellview.animals) > 0:
            for animal in cellview.animals:
                if (
                    (animal.species_id, animal.gender) not in self.internal_ark
                    and animal.species_id not in self.complete_species
                    and (animal.species_id, animal.gender)
                    not in [(a.species_id, a.gender) for a in self.flock]
                ):
                    # # This means the random_player will even attempt t
                    # # (unsuccessfully) obtain animals in other helpers' flocks
                    # random_animal = choice(tuple(cellview.animals))
                    return Obtain(animal)
            # direction = self._get_random_location()
            self.mode = "move_away"
            # self.direction = direction
            self.countdown = 10
            return Move(*self.move_towards(*self.direction))

        """If I see any animals that might not be in the arc, I'll chase the 
        closest one"""
        closest_animal = self._find_closest_animal()
        if closest_animal:
            # This means the random_player will even approach
            # animals in other helpers' flocks
            # print(f"[Clock {self.clock}] Player {self.id} moving toward animal at {closest_animal} from {self.position}")
            return Move(*self.move_towards(*closest_animal))

        # Systematic grid exploration (w/ zig-zag path)
        if self.mode == "waiting":
            # Pick a new grid cell to explore
            direction = self._get_next_grid_target()
            self.mode = "moving"
            # ZIG ZAG PATH
            self.zigzag_path = self.make_zigzag_path(
                self.position, direction, steps=15, amplitude=20
            )
            self.direction = self.zigzag_path.pop(0)
            # ZIG ZAG PATH
            return Move(*self.move_towards(*self.direction))
        else:
            # Check if we've reached our target grid cell
            if self.current_target_cell:
                current_grid = self._get_grid_cell(*self.position)
                if current_grid == self.current_target_cell:
                    # Reached target, pick new cell
                    direction = self._get_next_grid_target()
                    self.mode = "moving"
                    self.direction = direction
                    return Move(*self.move_towards(*self.direction))

            # Check if close to direction target
            if distance(*self.position, *self.direction) < 10:
                # Pick next path in zig zag grid cell
                if self.zigzag_path:
                    self.direction = self.zigzag_path.pop(0)
                    return Move(*self.move_towards(*self.direction))

                # No more zig zag path, pick new grid cell
                direction = self._get_next_grid_target()
                self.zigzag_path = self.make_zigzag_path(
                    self.position, direction, steps=15, amplitude=20
                )
                self.mode = "moving"
                self.direction = self.zigzag_path.pop(0)
                return Move(*self.move_towards(*self.direction))
            else:
                # Keep moving toward current target
                return Move(*self.move_towards(*self.direction))
