from __future__ import annotations


import math
from math import hypot, atan2, pi
from random import random, choice


from core.action import Action, Move, Obtain
from core.message import Message
from core.player import Player
from core.snapshots import HelperSurroundingsSnapshot
from core.views.player_view import Kind
from core.views.cell_view import CellView


class Player1(Player):
    """
    new behavior:
    - helpers explore more toward the most open space (away from  edges)
    - when an animal is seen in sight radius, immediately get it




    - Message: either
        * HELLO: announce own helper id (for basic presence info), or
        * SIGHTING: encode a high-value species + coarse direction bucket.
    - When it's raining: go straight to the Ark.
    - When carrying animals: go to the Ark to unload.
    - On a cell with animals: obtain the best (rarest / missing-gender) animal.
    - If animals are in sight: move towards the best animal cell (ALWAYS prioritized)
    - Otherwise: explore toward open space based on ark position
    """

    MAP_SIZE = 1000.0  # 1000km x 1000km
    MAX_FLOCK = 4

    # Messaging format (1 byte):
    #   If bit 7 == 0: HELLO message
    #       bits 0-2: helper_id_mod_8
    #   If bit 7 == 1: SIGHTING message
    #       bits 4-6: direction bucket (0..7) relative to Ark
    #       bits 0-3: species index bucket (0..15) based on rarity

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

        # Basic stuff
        self.is_raining: bool = False
        self.hellos_received: list[int] = []

        # Track time (check_surroundings is called once per turn)
        self.turn: int = 0

        # Copy species populations and build rarity info
        self.species_populations: dict[str, int] = dict(species_populations)
        self._init_species_metadata()

        # Ark-known genders for each species: {species: {"M", "F"}}
        self.ark_known: dict[str, set[str]] = {
            s: set() for s in self.species_populations
        }

        # Remember helper count for exploration partitioning
        self.num_helpers: int = num_helpers

        # NEW: Calculate exploration direction based on ark position and available space
        self._init_space_aware_exploration_direction()

        # Override exploration direction when see high-value sighting messages
        self.override_dir: tuple[float, float] | None = None
        self.override_dir_expire_turn: int = -1

    def _init_species_metadata(self) -> None:
        """Precompute rarity-based indices for species."""
        pops = list(self.species_populations.values())
        total_pop = sum(pops) if pops else 0
        self.default_population = (total_pop / len(pops)) if pops else 10.0

        # Rarer species (smaller population) get smaller indices
        self.species_by_rarity = sorted(
            self.species_populations.keys(),
            key=lambda s: self.species_populations[s],
        )
        self.species_index: dict[str, int] = {
            s: i for i, s in enumerate(self.species_by_rarity)
        }

    def _init_space_aware_exploration_direction(self) -> None:
        """
        Assign each helper a deterministic exploration direction based on:
        1. Ark position relative to map center
        2. Available space in each direction
        3. Helper ID for distribution

        Helpers explore toward the most open space (away from map edges).
        """
        if self.kind == Kind.Noah or self.num_helpers <= 0:
            self.base_explore_dir = (0.0, 0.0)
            return

        ark_x, ark_y = self.ark_position
        map_center = self.MAP_SIZE / 2.0

        if ark_x == map_center and ark_y == map_center:
            # Ark is in center; explore randomly
            angle = 2.0 * pi * (self.id / self.num_helpers)
            self.base_explore_dir = (math.cos(angle), math.sin(angle))
            return
        # Calculate distances to each edge from ark
        dist_to_left = ark_x
        dist_to_right = self.MAP_SIZE - ark_x
        dist_to_bottom = ark_y
        dist_to_top = self.MAP_SIZE - ark_y

        # Find the direction with the most space

        # Determine which quadrant has the most total space
        space_scores = {
            (1.0, 1.0): dist_to_right + dist_to_top,  # Top-right
            (1.0, -1.0): dist_to_right + dist_to_bottom,  # Bottom-right
            (-1.0, 1.0): dist_to_left + dist_to_top,  # Top-left
            (-1.0, -1.0): dist_to_left + dist_to_bottom,  # Bottom-left
        }

        # Find the quadrant with maximum space
        best_quadrant = max(space_scores.keys(), key=lambda k: space_scores[k])

        # Distribute helpers within the best quadrant(s)
        # Each helper gets a slightly different angle within the preferred direction
        idx = self.id % self.num_helpers

        # Create a base angle pointing toward the most open space
        base_angle = atan2(best_quadrant[1], best_quadrant[0])

        # Spread helpers within a 90-degree cone (pi/2 radians) around the base angle
        spread = (pi / 2.0) * (idx / max(self.num_helpers - 1, 1)) - (pi / 4.0)
        final_angle = base_angle + spread

        self.base_explore_dir = (math.cos(final_angle), math.sin(final_angle))

    # -------------------------------------------------------------------------
    # Generic helpers
    # -------------------------------------------------------------------------

    def _on_ark(self) -> bool:
        """Return True if the helper is currently on the Ark cell."""
        xcell, ycell = map(int, self.position)
        ax, ay = self.ark_position
        return xcell == ax and ycell == ay

    def _normalize_gender(self, gender) -> str | None:
        """Map gender field to 'M' or 'F' if possible."""
        if gender is None:
            return None
        g = str(gender).upper()
        if g.startswith("M"):
            return "M"
        if g.startswith("F"):
            return "F"
        return None

    def _sync_ark_info(self, snapshot: HelperSurroundingsSnapshot) -> None:
        """
        Attempt to refresh ark_known from snapshot.


        This gracefully does nothing if the simulator doesn't expose ark info.
        """
        # Try some plausible attribute names; ignore if missing
        ark_animals = getattr(snapshot, "ark_animals", None)
        if ark_animals is None:
            ark_animals = getattr(snapshot, "ark_contents", None)

        if ark_animals is None:
            # cannot see the actual ark content via snapshot; fall back on
            # whatever have inferred so far (delivered animals, etc.).
            return

        for a in ark_animals:
            species = getattr(a, "species", None)
            gender = self._normalize_gender(getattr(a, "gender", None))
            if not species or not gender:
                continue
            self.ark_known.setdefault(species, set()).add(gender)

    def _get_my_cell(self) -> CellView:
        """Return the CellView corresponding to the helper's current position."""
        xcell, ycell = map(int, self.position)

        if not self.sight.cell_is_in_sight(xcell, ycell):
            raise RuntimeError(f"{self} failed to find own cell at {(xcell, ycell)}")

        return self.sight.get_cellview_at(xcell, ycell)

    def _species_interest(self, species: str, gender: str | None = None) -> float:
        """
        Numeric priority for a species (and optionally gender), higher is better.


        - Favors rarer species (smaller population).
        - Strongly favors genders not yet present on the ark for that species.
        """
        pop = self.species_populations.get(species, self.default_population)
        rarity_score = 0.0 if pop <= 0 else 1.0 / pop

        genders_on_ark = self.ark_known.get(species, set())
        bonus = 0.0

        if len(genders_on_ark) == 0:
            # Species not on ark at all
            bonus += 3.0
        elif len(genders_on_ark) == 1:
            # Only one gender present
            if gender is not None and gender not in genders_on_ark:
                # Missing this gender: big bonus
                bonus += 2.0
            else:
                # Species present but incomplete
                bonus += 1.0
        else:
            # Species already fully represented
            bonus += 0.0

        return bonus + rarity_score

    def _cell_interest(self, cellview: CellView) -> float:
        """Interest of a cell based on best species within it (ignores gender at distance)."""
        best = 0.0
        for animal in cellview.animals:
            species = getattr(animal, "species", None)
            if species is None:
                continue
            val = self._species_interest(species, gender=None)
            if val > best:
                best = val
        return best

    def _find_best_animal_cell(self) -> tuple[int, int] | None:
        """
        NEW: Find the best cell to chase based on species interest and distance.
        Now ALWAYS returns the closest animal if any are visible, prioritizing capture.


        Returns:
            (x, y) of the chosen cell, or None if no animals are in sight.
        """
        best_pos: tuple[int, int] | None = None
        best_score: float | None = None
        my_x, my_y = self.position

        for cellview in self.sight:
            if not cellview.animals:
                continue

            # Get base interest for this cell
            base_interest = self._cell_interest(cellview)

            # Even if interest is low, still want to check animals
            # Give minimum interest of 0.1 to any cell with animals
            if base_interest <= 0.0:
                base_interest = 0.1

            dist = hypot(my_x - cellview.x, my_y - cellview.y)

            # NEW: Heavily weight closer animals to prioritize immediate capture
            # Distance penalty is much stronger now
            score = base_interest / (0.1 + dist)

            if best_score is None or score > best_score:
                best_score = score
                best_pos = (cellview.x, cellview.y)

        return best_pos

    def _any_animals_in_sight(self) -> bool:
        """
        NEW: Quick check if there are any animals visible in sight radius.

        Returns:
            bool: True if at least one animal is visible
        """
        for cellview in self.sight:
            if cellview.animals:
                return True
        return False

    def _get_random_move(self, max_tries: int = 32) -> tuple[float, float]:
        """
        Sample a random valid move from current position.


        If no valid random move is found within max_tries, stay put.
        """
        old_x, old_y = self.position

        for _ in range(max_tries):
            dx, dy = random() - 0.5, random() - 0.5
            new_x, new_y = old_x + dx, old_y + dy
            if self.can_move_to(new_x, new_y):
                return new_x, new_y

        # Fallback: don't move if everything failed (should be rare).
        return old_x, old_y

    def _direction_from_bucket(self, bucket: int) -> tuple[float, float]:
        """Convert direction bucket (0..7) into a unit vector."""
        bucket = bucket % 8
        angle = 2.0 * pi * (bucket / 8.0)
        return math.cos(angle), math.sin(angle)

    def _bucket_from_direction(self, dx: float, dy: float) -> int:
        """Convert a vector into a direction bucket (0..7)."""
        angle = atan2(dy, dx)
        if angle < 0:
            angle += 2.0 * pi
        bucket = int((angle / (2.0 * pi)) * 8.0) % 8
        return bucket

    def _get_exploration_direction(self) -> tuple[float, float]:
        """
        Decide which direction to explore:
        - Use override_dir if a recent sighting.
        - Otherwise use the helper's space-aware base direction.
        """
        if self.override_dir is not None and self.turn <= self.override_dir_expire_turn:
            return self.override_dir

        return self.base_explore_dir

    def _get_exploration_move(self) -> tuple[float, float]:
        """
        Move roughly along this helper's exploration direction, staying within
        the map and falling back to a random move if blocked.

        NEW: Uses space-aware direction that accounts for ark position.
        """
        dir_x, dir_y = self._get_exploration_direction()

        # If no have a meaningful exploration direction, just wander randomly.
        if (dir_x, dir_y) == (0.0, 0.0):
            return self._get_random_move()

        old_x, old_y = self.position
        step = 1.0  # max 1km per turn
        target_x = old_x + dir_x * step
        target_y = old_y + dir_y * step

        # Clamp to map bounds
        target_x = min(max(target_x, 0.0), self.MAP_SIZE - 1e-6)
        target_y = min(max(target_y, 0.0), self.MAP_SIZE - 1e-6)

        if self.can_move_to(target_x, target_y):
            return target_x, target_y

        # If blocked, try a random move instead
        return self._get_random_move()

    def _choose_best_animal_in_cell(self, cellview: CellView):
        """
        Among animals in the current cell, pick the one with highest value.


        Value depends on species rarity and whether the gender is needed on the ark.
        """
        best_animal = None
        best_val: float | None = None

        for animal in cellview.animals:
            species = getattr(animal, "species", None)
            gender_raw = getattr(animal, "gender", None)
            if species is None:
                continue
            gender = self._normalize_gender(gender_raw)
            val = self._species_interest(species, gender)
            if best_val is None or val > best_val:
                best_val = val
                best_animal = animal

        # Fallback if couldn't compute a value for some reason
        if best_animal is None and cellview.animals:
            best_animal = choice(tuple(cellview.animals))

        return best_animal

    def _encode_hello(self) -> int:
        """Encode a HELLO message with own helper id mod 8."""
        helper_id_mod8 = self.id % 8
        msg = helper_id_mod8 & 0b00000111  # ensure bits 0-2 only
        return msg  # bit 7 = 0 => HELLO

    def _encode_sighting(self, species: str, cell_x: int, cell_y: int) -> int:
        """
        Encode a high-value sighting into one byte:


        bit 7 = 1 (SIGHTING)
        bits 4-6: direction bucket (0..7) from Ark to sighting cell
        bits 0-3: species index bucket (0..15) based on rarity
        """
        ax, ay = self.ark_position
        dx = cell_x - ax
        dy = cell_y - ay
        if dx == 0 and dy == 0:
            # Arbitrary direction if exactly at Ark
            dx, dy = 1.0, 0.0

        dir_bucket = self._bucket_from_direction(dx, dy) & 0b00000111

        idx = self.species_index.get(species, 0)
        species_bucket = idx % 16  # 0..15

        msg = 0x80  # bit 7 = 1
        msg |= dir_bucket << 4
        msg |= species_bucket & 0x0F
        return msg & 0xFF

    def _decode_sighting(self, msg_val: int) -> tuple[int, int]:
        """
        Decode sighting message (assumes bit 7 == 1).
        Returns (dir_bucket, species_bucket).
        """
        dir_bucket = (msg_val >> 4) & 0b00000111
        species_bucket = msg_val & 0x0F
        return dir_bucket, species_bucket

    def _species_from_bucket(self, bucket: int) -> str | None:
        """Map species bucket back to a species name, if possible."""
        if not self.species_by_rarity:
            return None
        idx = bucket % len(self.species_by_rarity)
        return self.species_by_rarity[idx]

    def _find_best_high_value_sighting_in_view(self) -> tuple[str, int, int] | None:
        """
            Using current sight, find a high-value (species, x, y) to advertise.


        choose a cell with at least one animal of a species that is:
            - not yet fully represented on the ark
            - and/or rare.
        """
        best_species: str | None = None
        best_x: int | None = None
        best_y: int | None = None
        best_score: float | None = None

        for cellview in self.sight:
            if not cellview.animals:
                continue

            for animal in cellview.animals:
                species = getattr(animal, "species", None)
                if species is None:
                    continue

                # Use species interest without gender (can't see gender at distance)
                interest = self._species_interest(species, gender=None)
                if best_score is None or interest > best_score:
                    best_score = interest
                    best_species = species
                    best_x, best_y = cellview.x, cellview.y

        if best_species is None:
            return None

        # Threshold: only advertise "high-value" sightings
        # Roughly: species not fully represented / rare.
        if best_score is not None and best_score < 0.2:
            return None

        return best_species, best_x, best_y  # type: ignore[arg-type]

    def _make_message(self) -> int:
        """
        Build outgoing message for this turn.


        - If  a high-value sighting: send SIGHTING.
        - Otherwise, send HELLO.
        """
        sighting = self._find_best_high_value_sighting_in_view()
        if sighting is not None:
            species, cx, cy = sighting
            msg = self._encode_sighting(species, cx, cy)
        else:
            msg = self._encode_hello()

        if not self.is_message_valid(msg):
            msg &= 0xFF

        return msg

    def check_surroundings(self, snapshot: HelperSurroundingsSnapshot) -> int:
        """
        Synchronize internal state with the simulator snapshot and
        compute the outgoing message for this turn.
        """
        self.turn += 1

        # Trust the simulator's view of reality
        self.position = snapshot.position
        self.flock = snapshot.flock
        self.sight = snapshot.sight
        self.is_raining = snapshot.is_raining

        # If on Ark, try to read back species/gender status from ark
        if self._on_ark():
            self._sync_ark_info(snapshot)

        return self._make_message()

    def get_action(self, messages: list[Message]) -> Action | None:
        """
        Decide the next action with priority given to visible animals.

        Action priority:
        1. If raining: return to ark
        2. If carrying animals: return to ark
        3. If on cell with animals: obtain best animal
        4. IF ANY ANIMALS IN SIGHT: chase the closest/best one (NEW - HIGHEST PRIORITY)
        5. Otherwise: explore toward open space

        Based on:
        - Received messages
        - Weather (raining)
        - Current flock and surroundings
        """

        # Process incoming messages
        for msg in messages:
            val = msg.contents & 0xFF
            if (val & 0x80) == 0:
                # HELLO message
                helper_id_mod8 = val & 0b00000111
                expected = msg.from_helper.id % 8
                if helper_id_mod8 == expected:
                    self.hellos_received.append(val)
            else:
                # SIGHTING message
                dir_bucket, species_bucket = self._decode_sighting(val)
                species = self._species_from_bucket(species_bucket)
                if species is None:
                    continue

                # If the species is still not fully represented on the ark,
                # bias exploration in that direction for some turns.
                genders = self.ark_known.get(species, set())
                if len(genders) < 2:
                    dir_vec = self._direction_from_bucket(dir_bucket)
                    self.override_dir = dir_vec
                    # Follow this sighting for ~50 turns
                    self.override_dir_expire_turn = self.turn + 50

        # Noah never moves (but still broadcasts in check_surroundings)
        if self.kind == Kind.Noah:
            return None

        # If it's raining, go to Ark ASAP
        if self.is_raining:
            return Move(*self.move_towards(*self.ark_position))

        # if carrying animals, prioritize getting them to the Ark
        if not self.is_flock_empty():
            return Move(*self.move_towards(*self.ark_position))

        # If  on top of any animals, try to obtain the best one
        cellview = self._get_my_cell()
        if cellview.animals and len(self.flock) < self.MAX_FLOCK:
            best_animal = self._choose_best_animal_in_cell(cellview)
            if best_animal is not None:
                return Obtain(best_animal)

        # If see ANY animals in sight, immediately chase them
        # This is now the highest priority after obtaining animals in current cell
        best_cell_pos = self._find_best_animal_cell()
        if best_cell_pos is not None:
            return Move(*self.move_towards(*best_cell_pos))

        # Otherwise, explore using space-aware direction
        return Move(*self._get_exploration_move())
