from __future__ import annotations

import math
from random import choice, random
from typing import Any

from core.action import Action, Move, Obtain
from core.message import Message
from core.player import Player
from core.snapshots import HelperSurroundingsSnapshot
from core.views.cell_view import CellView
from core.views.player_view import Kind


def distance(x1: float, y1: float, x2: float, y2: float) -> float:
    return (abs(x1 - x2) ** 2 + abs(y1 - y2) ** 2) ** 0.5


class Player9(Player):
    FLOCK_CAPACITY = 4

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

        self.is_raining = False
        self.hellos_received: list[int] = []
        self.num_helpers = num_helpers

        # Initialize ark_inventory so the linter is happy.
        self.ark_inventory: dict[str, set[str]] = {}

        # --- Communication and Targeting ---
        self.noah_target_species: str | None = None

        # Sort species from rarest to commonest
        self.rarity_order = sorted(
            species_populations.keys(), key=lambda s: species_populations.get(s, 0)
        )

        # Create a mapping for 1-byte messages
        self.int_to_species: dict[int, str] = {
            i + 1: species for i, species in enumerate(self.rarity_order)
        }
        self.species_to_int: dict[str, int] = {
            species: i for i, species in self.int_to_species.items()
        }

        # Each helper gets its own sweep direction (angle) so they fan out.
        if num_helpers > 0:
            idx = id % num_helpers
            self.sweep_angle = 2.0 * math.pi * idx / num_helpers
        else:
            self.sweep_angle = 0.0

        if self.kind == Kind.Noah:
            print("I am Noah. I will coordinate.")
        else:
            print(f"I am Helper {self.id}. My sweep angle is {self.sweep_angle:.2f}")

    # ---------- Core Helper Functions ----------

    def _get_my_cell(self) -> CellView:
        xcell, ycell = tuple(map(int, self.position))
        if not self.sight.cell_is_in_sight(xcell, ycell):
            raise Exception(f"{self} failed to find own cell")
        return self.sight.get_cellview_at(xcell, ycell)

    # --- Robust "un-stuck" function ---
    def _get_random_move(self) -> tuple[float, float]:
        """
        Tries 10 times to find a valid random move.
        If it fails, it tries to move to center, then to ark,
        then stays put. This is to prevent any freezes.
        """
        old_x, old_y = self.position

        # 1. Try 10 random moves
        for _ in range(10):
            dx, dy = random() - 0.5, random() - 0.5
            new_x, new_y = old_x + dx, old_y + dy
            if self.can_move_to(new_x, new_y):
                return new_x, new_y

        # 2. Fallback 1: Try to move to the center
        new_x, new_y = self.move_towards(500.0, 500.0)
        if self.can_move_to(new_x, new_y):
            return new_x, new_y

        # 3. Fallback 2: Try to move to the Ark
        new_x, new_y = self.move_towards(*self.ark_position)
        if self.can_move_to(new_x, new_y):
            return new_x, new_y

        # 4. Fallback 3: Stay put (absolute last resort)
        return old_x, old_y

    # ---------- Coordinated Hunting Logic ----------

    def _find_rarest_needed_species(self) -> str | None:
        """(Noah's logic) Finds the rarest species we don't have 2 of."""
        for species in self.rarity_order:
            if species not in self.ark_inventory:
                return species  # We have none
            if len(self.ark_inventory.get(species, set())) < 2:
                return species  # We only have one gender
        return None  # We have saved all species!

    def _get_best_animal_on_cell(self, cellview: CellView) -> Any | None:
        """(Helper logic) Finds the best animal to Obtain on the current cell."""
        if not cellview.animals:
            return None

        target_animal = None
        # Priority 1: Get the animal Noah wants
        if self.noah_target_species:
            for animal in cellview.animals:
                species_name = str(animal).split(" ")[0]
                if species_name == self.noah_target_species:
                    target_animal = animal
                    break

        if target_animal:
            return target_animal

        # Priority 2: No target, or target not here. Just grab one.
        return choice(tuple(cellview.animals))

    def _find_best_animal_to_chase(self) -> tuple[int, int] | None:
        """(Helper logic) Finds the best animal to chase in sight."""
        target_cells: list[tuple[float, tuple[int, int]]] = []
        any_cells: list[tuple[float, tuple[int, int]]] = []

        for cellview in self.sight:
            if not cellview.animals:
                continue

            dist = distance(*self.position, cellview.x, cellview.y)
            has_target = False

            if self.noah_target_species:
                for animal in cellview.animals:
                    species_name = str(animal).split(" ")[0]
                    if species_name == self.noah_target_species:
                        target_cells.append((dist, (cellview.x, cellview.y)))
                        has_target = True
                        break

            if not has_target:
                any_cells.append((dist, (cellview.x, cellview.y)))

        # Priority 1: Go for the closest cell that has our target
        if target_cells:
            target_cells.sort(key=lambda x: x[0])  # Sort by distance
            return target_cells[0][1]  # Return (x, y)

        # Priority 2: No target in sight. Go for the closest *any* animal.
        if any_cells:
            any_cells.sort(key=lambda x: x[0])  # Sort by distance
            return any_cells[0][1]  # Return (x, y)

        return None

    # ---------- Sweep & Bounce Logic (No Jitter) ----------

    def _get_sweep_move(self) -> tuple[float, float]:
        old_x, old_y = self.position

        base_dx = math.cos(self.sweep_angle)
        base_dy = math.sin(self.sweep_angle)

        reflected = False
        if (old_x < 5.0 and base_dx < 0.0) or (old_x > 995.0 and base_dx > 0.0):
            base_dx = -base_dx
            reflected = True

        if (old_y < 5.0 and base_dy < 0.0) or (old_y > 995.0 and base_dy > 0.0):
            base_dy = -base_dy
            reflected = True

        if reflected:
            self.sweep_angle = math.atan2(base_dy, base_dx)

        dx = base_dx
        dy = base_dy

        length = math.sqrt(dx * dx + dy * dy)
        if length == 0.0:
            return self._get_random_move()

        dx /= length
        dy /= length

        new_x = old_x + dx
        new_y = old_y + dy

        if not self.can_move_to(new_x, new_y):
            # The deterministic sweep is illegal, so we are stuck.
            # Call the robust random-move fallback.
            return self._get_random_move()

        return new_x, new_y

    # ---------- MAIN HOOKS (Updated) ----------

    def check_surroundings(self, snapshot: HelperSurroundingsSnapshot) -> int:
        """
        Called by the simulator for *both* Noah and Helpers.
        Noah broadcasts. Helpers sync.
        """
        if self.kind == Kind.Noah:
            # --- NOAH'S LOGIC ---
            target_species = self._find_rarest_needed_species()
            if target_species:
                msg = self.species_to_int.get(target_species, 0)
                return msg
            else:
                return 0  # 0 = "Get anything"

        else:
            # --- HELPER'S LOGIC ---
            self.position = snapshot.position
            self.flock = snapshot.flock
            self.sight = snapshot.sight
            self.is_raining = snapshot.is_raining

            # Simple "hello" protocol
            if len(self.hellos_received) == 0:
                msg = 1 << (self.id % 8)
            else:
                msg = 0
                for hello in self.hellos_received:
                    msg |= hello
                self.hellos_received = []

            if not self.is_message_valid(msg):
                msg = msg & 0xFF

            return msg

    def get_action(self, messages: list[Message]) -> Action | None:
        """
        Called by the simulator for *both* Noah and Helpers.
        Noah does nothing. Helpers act.
        """

        if self.kind == Kind.Noah:
            return None  # Noah doesn't move or act

        # --- HELPER'S LOGIC ---

        # 1. Listen for Noah's broadcast
        for msg in messages:
            if msg.from_helper.kind == Kind.Noah:
                self.noah_target_species = self.int_to_species.get(msg.contents)
                break

        # 2. Handle "Hello" messages
        for msg in messages:
            if msg.from_helper.kind == Kind.Helper:
                if 1 << (msg.from_helper.id % 8) == msg.contents:
                    self.hellos_received.append(msg.contents)

        # 3. Decide on an Action

        # Priority 1: Safety / Flood Awareness / Full Inventory
        if self.is_raining:
            # Raining = flood is spreading → get to Ark ASAP
            return Move(*self.move_towards(*self.ark_position))

        # If the game exposes time until flood or similar:
        if hasattr(self, "time_remaining"):
            # If far away from the ark, start returning before the flood kills the helper
            dist_to_ark = distance(*self.position, *self.ark_position)
            if dist_to_ark > 40:
                return Move(*self.move_towards(*self.ark_position))

        # *** Priority 2: THIS IS THE FIX (Reverted) ***
        # If we have *any* animal, return to score.
        # This avoids the sweep bug and scores points.
        if len(self.flock) > 0:
            return Move(*self.move_towards(*self.ark_position))

        # Priority 3: Obtain animal if on a cell with one
        cellview = self._get_my_cell()
        if len(self.flock) < self.FLOCK_CAPACITY and len(cellview.animals) > 0:
            animal_to_get = self._get_best_animal_on_cell(cellview)
            if animal_to_get:
                return Obtain(animal_to_get)

        # Priority 4: Chase the "best" animal in sight
        best_animal_pos = self._find_best_animal_to_chase()
        if best_animal_pos:
            return Move(*self.move_towards(*best_animal_pos))

        # Priority 5: No animals in sight, sweep the grid
        new_x, new_y = self._get_sweep_move()
        return Move(new_x, new_y)
