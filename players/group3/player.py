import math
import random
from core.action import Action, Move, Obtain
from core.animal import Animal
from core.message import Message
from core.player import Player
from core.snapshots import HelperSurroundingsSnapshot
from core.views.player_view import Kind
import core.constants as c


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
        self.ark_x = ark_x
        self.ark_y = ark_y
        self.my_angle = None  # My exploration angle
        self.snapshot = None
        self.caught_species = {}  # {species_id: {'M': bool, 'F': bool}}
        self.last_10_positions = []  # Track last 10 positions to detect stuck state
        self.max_safe_distance = 840  # Max distance from ark to ensure we can return (1008 turns / 1.2 safety)
        self.first_trip_complete = False  # Track if we've returned to ark at least once

    def need_animal(self, species_id: int, gender_name: str) -> bool:
        """Check if we need this species/gender combination."""
        # Only check for known genders
        if gender_name not in ["Male", "Female"]:
            return False  # Can't determine if we need Unknown gender

        gender_key = "M" if gender_name == "Male" else "F"

        if species_id not in self.caught_species:
            return True

        return not self.caught_species[species_id].get(gender_key, False)

    def mark_caught(self, species_id: int, gender_name: str):
        """Mark that we've caught this species/gender."""
        # Only mark known genders
        if gender_name not in ["Male", "Female"]:
            return  # Can't mark Unknown gender

        gender_key = "M" if gender_name == "Male" else "F"

        if species_id not in self.caught_species:
            self.caught_species[species_id] = {"M": False, "F": False}

        self.caught_species[species_id][gender_key] = True

    def find_needed_animal(
        self, snapshot: HelperSurroundingsSnapshot
    ) -> tuple[int, int, Animal] | None:
        """Find closest animal that we need (haven't caught both genders)."""
        best_animal = None
        best_distance = float("inf")

        for cell_view in snapshot.sight:
            for animal in cell_view.animals:
                # Can only see gender if in same cell
                current_cell_x = int(self.position[0])
                current_cell_y = int(self.position[1])

                if cell_view.x == current_cell_x and cell_view.y == current_cell_y:
                    # We can see the gender, check if we need it
                    if self.need_animal(animal.species_id, animal.gender.name):
                        return (cell_view.x, cell_view.y, animal)
                else:
                    # Can't see gender from distance, but check if we might need this species
                    # If we need either gender of this species, consider it
                    if animal.species_id not in self.caught_species:
                        # Haven't caught any of this species yet
                        dx = cell_view.x + 0.5 - self.position[0]
                        dy = cell_view.y + 0.5 - self.position[1]
                        distance = math.sqrt(dx * dx + dy * dy)

                        if distance < best_distance:
                            best_distance = distance
                            best_animal = (cell_view.x, cell_view.y, animal)
                    elif not (
                        self.caught_species[animal.species_id].get("M", False)
                        and self.caught_species[animal.species_id].get("F", False)
                    ):
                        # Have caught one gender but not both
                        dx = cell_view.x + 0.5 - self.position[0]
                        dy = cell_view.y + 0.5 - self.position[1]
                        distance = math.sqrt(dx * dx + dy * dy)

                        if distance < best_distance:
                            best_distance = distance
                            best_animal = (cell_view.x, cell_view.y, animal)

        return best_animal

    def get_distance_from_ark(self) -> float:
        """Calculate current distance from ark."""
        # Position is always at integer coordinates
        dx = int(self.position[0]) - self.ark_x
        dy = int(self.position[1]) - self.ark_y
        return math.sqrt(dx * dx + dy * dy)

    def is_safe_to_move(self, new_x: float, new_y: float) -> bool:
        """Check if moving to new position is safe (can still return in time)."""
        # Calculate distance from new position to ark
        dx = new_x - self.ark_x
        dy = new_y - self.ark_y
        new_distance = math.sqrt(dx * dx + dy * dy)

        # Don't venture beyond max safe distance
        return new_distance <= self.max_safe_distance

    def is_stuck_in_vicinity(self) -> bool:
        """Check if stuck in same area for last 10 turns."""
        if len(self.last_10_positions) < 10:
            return False

        # Calculate the centroid of last 10 positions
        avg_x = sum(x for x, y in self.last_10_positions) / 10
        avg_y = sum(y for x, y in self.last_10_positions) / 10

        # Check if all positions are within 10km radius of centroid
        max_distance_from_center = 0
        for x, y in self.last_10_positions:
            distance = math.sqrt((x - avg_x) ** 2 + (y - avg_y) ** 2)
            max_distance_from_center = max(max_distance_from_center, distance)

        # If all positions within 10km radius, we're stuck chasing
        return max_distance_from_center <= 10

    def move_toward_ark(self) -> Move:
        """Move up to 1km toward the ark (integer coordinates only)."""
        # Current position as integers
        curr_x = int(self.position[0])
        curr_y = int(self.position[1])

        dx = self.ark_x - curr_x
        dy = self.ark_y - curr_y
        distance = math.sqrt(dx * dx + dy * dy)

        if distance == 0:
            return Move(curr_x, curr_y)

        # Move up to 1km toward ark
        scale = min(1.0, distance) / distance
        new_x = curr_x + dx * scale
        new_y = curr_y + dy * scale

        # Round to integer coordinates
        new_x = round(new_x)
        new_y = round(new_y)

        return Move(float(new_x), float(new_y))

    def check_surroundings(self, snapshot: HelperSurroundingsSnapshot) -> int:
        # Store snapshot
        self.snapshot = snapshot

        # Set my angle on first turn
        if self.my_angle is None:
            # Each helper gets a unique direction
            self.my_angle = (self.id / self.num_helpers) * 2 * math.pi

        # Detect successful delivery BEFORE updating flock
        # (flock changes from non-empty to empty when we unload at ark)
        if snapshot.ark_view is not None:
            current_cell_x = int(snapshot.position[0])
            current_cell_y = int(snapshot.position[1])
            if current_cell_x == self.ark_x and current_cell_y == self.ark_y:
                # We're at the ark - check if we just unloaded
                if len(self.flock) > 0 and len(snapshot.flock) == 0:
                    # Flock went from non-empty to empty = successful delivery
                    self.first_trip_complete = True

        # Update position and flock
        self.position = snapshot.position
        self.flock = snapshot.flock

        # Sync with Ark contents whenever we can see it
        if snapshot.ark_view is not None:
            for animal in snapshot.ark_view.animals:
                # Animals on ark have known genders
                self.mark_caught(animal.species_id, animal.gender.name)

        # Track last 10 positions
        self.last_10_positions.append((self.position[0], self.position[1]))
        if len(self.last_10_positions) > 10:
            self.last_10_positions.pop(0)  # Keep only last 10

        return 0

    def get_action(self, messages: list[Message]) -> Action | None:
        """Move radially outward, chase animals we need, catch them, come back."""
        if self.kind == Kind.Noah:
            return None

        if not self.snapshot or self.my_angle is None:
            return None

        current_cell_x = int(self.position[0])
        current_cell_y = int(self.position[1])

        # Try to catch animal if in same cell and have room
        if len(self.flock) < 4:
            for cell_view in self.snapshot.sight:
                if cell_view.x == current_cell_x and cell_view.y == current_cell_y:
                    for animal in cell_view.animals:
                        # Safety check: only catch if gender is known (should always be true in same cell)
                        if animal.gender.name not in ["Male", "Female"]:
                            continue  # Skip Unknown genders

                        # Check if we need this animal
                        if self.need_animal(animal.species_id, animal.gender.name):
                            # Mark it as caught
                            self.mark_caught(animal.species_id, animal.gender.name)
                            return Obtain(animal)

        # Return to ark conditions:
        # - First trip: 2 animals (quick sync with ark)
        # - Later trips: 4 animals (max capacity)
        # - Always return if raining
        target_flock_size = 2 if not self.first_trip_complete else 4
        if len(self.flock) >= target_flock_size or self.snapshot.is_raining:
            return self.move_toward_ark()

        # Check if stuck in same vicinity for last 10 turns
        if self.is_stuck_in_vicinity():
            # Stop chasing, clear position history, and move forward
            self.last_10_positions.clear()
            # Will continue with normal radial exploration below

        # Look for animals we need (only if not stuck)
        elif len(self.flock) < 4:
            animal_target = self.find_needed_animal(self.snapshot)

            if animal_target:
                target_x, target_y, animal = animal_target

                # Current position as integers
                curr_x = int(self.position[0])
                curr_y = int(self.position[1])

                # Move toward animal (animal is at integer coordinates)
                dx = target_x - curr_x
                dy = target_y - curr_y
                distance = math.sqrt(dx * dx + dy * dy)

                if distance > 0:
                    # Move up to 1km toward target
                    scale = min(1.0, distance) / distance
                    new_x = curr_x + dx * scale
                    new_y = curr_y + dy * scale

                    # Round to integer coordinates
                    new_x = round(new_x)
                    new_y = round(new_y)

                    new_x = max(0, min(c.X - 1, new_x))
                    new_y = max(0, min(c.Y - 1, new_y))

                    # Only chase if it's safe to do so
                    if self.is_safe_to_move(new_x, new_y):
                        return Move(float(new_x), float(new_y))

        # Default: Move radially outward
        # Current position as integers
        curr_x = int(self.position[0])
        curr_y = int(self.position[1])

        # Check if another helper is at our current position
        for cell_view in self.snapshot.sight:
            if cell_view.x == curr_x and cell_view.y == curr_y:
                for helper_view in cell_view.helpers:
                    if helper_view.id != self.id and helper_view.kind == Kind.Helper:
                        # Another helper is here! Adjust our angle to spread out
                        self.my_angle += math.radians(30)  # Turn 30 degrees
                        self.my_angle %= 2 * math.pi
                        break

        dx = math.cos(self.my_angle)
        dy = math.sin(self.my_angle)

        new_x = curr_x + dx
        new_y = curr_y + dy

        # Round to integer coordinates
        new_x = round(new_x)
        new_y = round(new_y)

        # Check if we hit a boundary and need to rebound
        hit_boundary = False
        if new_x <= 0 or new_x >= c.X - 1:
            # Hit left or right boundary - reflect angle horizontally
            self.my_angle = math.pi - self.my_angle
            hit_boundary = True
        if new_y <= 0 or new_y >= c.Y - 1:
            # Hit top or bottom boundary - reflect angle vertically
            self.my_angle = -self.my_angle
            hit_boundary = True

        # Normalize angle to [0, 2π)
        self.my_angle = self.my_angle % (2 * math.pi)

        # If we hit a boundary, recalculate movement with new angle
        if hit_boundary:
            dx = math.cos(self.my_angle)
            dy = math.sin(self.my_angle)
            new_x = curr_x + dx
            new_y = curr_y + dy
            new_x = round(new_x)
            new_y = round(new_y)

        # Clamp to grid boundaries
        new_x = max(0, min(c.X - 1, new_x))
        new_y = max(0, min(c.Y - 1, new_y))

        # Safety check: Don't move if it would take us too far from ark
        if not self.is_safe_to_move(new_x, new_y):
            # Too far from ark, bounce back inward
            # Reflect angle to point more toward ark
            ark_dx = self.ark_x - curr_x
            ark_dy = self.ark_y - curr_y
            ark_angle = math.atan2(ark_dy, ark_dx)

            # Bounce: reflect our angle toward the ark
            # Add some randomness (±45 degrees) so helpers explore different areas
            offset = random.uniform(-math.pi / 4, math.pi / 4)
            self.my_angle = ark_angle + offset

            # Recalculate move with new angle
            dx = math.cos(self.my_angle)
            dy = math.sin(self.my_angle)
            new_x = curr_x + dx
            new_y = curr_y + dy
            new_x = round(new_x)
            new_y = round(new_y)
            new_x = max(0, min(c.X - 1, new_x))
            new_y = max(0, min(c.Y - 1, new_y))

        return Move(float(new_x), float(new_y))
