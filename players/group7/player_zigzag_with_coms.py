"""Player7: Army formation sweep with communication protocol."""

from __future__ import annotations
import heapq

from core.action import Action, Move, Obtain
from core.message import Message
from core.player import Player
from core.snapshots import HelperSurroundingsSnapshot
from core.views.player_view import Kind
import core.constants as c


class Player7(Player):
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

        # Communication protocol (from comms_player)
        self.priorities: set[tuple[int, int]] = set()
        self.messages_sent: set[int] = set()
        self.messages_to_send: list[int] = []
        self.last_seen_ark_animals: set[tuple[int, int]] = set()

        # Strip-based exploration
        self.strip_width = 10  # Width of each helper's strip
        self.my_strip_start = self.id * self.strip_width
        self.my_strip_end = (self.id + 1) * self.strip_width
        # Ensure within bounds
        self.my_strip_start = min(self.my_strip_start, int(c.X) - 1)
        self.my_strip_end = min(self.my_strip_end, int(c.X))

        # Zigzag state
        self.at_strip = False  # Whether helper has reached their strip
        self.going_down = True  # Direction of vertical movement
        self.sweep_row = 0  # Current row being swept
        self.row_height = 5.0  # Height of each zigzag row (5km)

        # State
        self.turn = 0
        self.is_raining = False

    def check_surroundings(self, snap: HelperSurroundingsSnapshot) -> int:
        self.turn += 1
        self.position = snap.position
        self.flock = snap.flock
        self.is_raining = snap.is_raining
        self.last_snapshot = snap  # Save for animal detection

        # Initialize priorities on first turn
        if self.turn == 1 and self.kind != Kind.Noah:
            for letter in self.species_populations.keys():
                sid = ord(letter) - ord("a")
                self.priorities.add((sid, 0))  # Male
                self.priorities.add((sid, 1))  # Female

        # Noah: just forward messages
        if self.kind == Kind.Noah:
            if self.messages_to_send:
                return heapq.heappop(self.messages_to_send)
            return 0

        # Process ark view for communication
        if snap.ark_view:
            current_ark = {
                (a.species_id, a.gender.value) for a in snap.ark_view.animals
            }
            new_animals = current_ark - self.last_seen_ark_animals

            for sid, gender in new_animals:
                self.priorities.discard((sid, gender))
                # Ark message: bits 3-7=species, bit 2=gender, bit 1=ARK
                msg = (sid << 3) | (gender << 2) | 0b00000010
                if msg not in self.messages_sent:
                    heapq.heappush(self.messages_to_send, msg)
                    self.messages_sent.add(msg)

            self.last_seen_ark_animals = current_ark

        # Send queued message
        if self.messages_to_send:
            return heapq.heappop(self.messages_to_send)

        return 0

    def get_action(self, messages: list[Message]) -> Action | None:
        if self.kind == Kind.Noah:
            return None

        # Process messages
        self._process_messages(messages)

        # Return to ark if raining or flock full
        if self.is_raining or len(self.flock) >= 4:
            if not self.is_in_ark():
                return Move(*self.move_towards(*self.ark_position))
            return None

        # Try to obtain priority animals at current location
        if hasattr(self, "last_snapshot") and self.last_snapshot:
            cx, cy = int(self.position[0]), int(self.position[1])
            for cv in self.last_snapshot.sight:
                if cv.x == cx and cv.y == cy:
                    # Found our cell, check for priority animals
                    for animal in cv.animals:
                        key = (animal.species_id, animal.gender.value)
                        if key in self.priorities and len(self.flock) < 4:
                            self.priorities.discard(key)
                            # Broadcast obtain message
                            msg = (
                                (animal.species_id << 3)
                                | (animal.gender.value << 2)
                                | 0b00000001
                            )
                            if msg not in self.messages_sent:
                                heapq.heappush(self.messages_to_send, msg)
                                self.messages_sent.add(msg)
                            return Obtain(animal)
                    break

        # Move in army formation
        return self._formation_move()

    def _process_messages(self, messages: list[Message]) -> None:
        """Process incoming messages and forward to neighbors."""
        for msg in messages:
            b = msg.contents

            # Decode: bit 1=ARK, bit 0=LOCAL, bit 2=gender, bits 3-7=species
            from_ark = bool(b & 0b00000010)
            from_local = bool(b & 0b00000001)
            gender = (b & 0b00000100) >> 2
            sid = (b & 0b11111000) >> 3

            key = (sid, gender)

            # Handle ark messages (release if we have it)
            if from_ark:
                for a in self.flock:
                    if a.species_id == sid and a.gender.value == gender:
                        self.priorities.discard(key)
                        break

            # Handle local messages (update priorities)
            if from_local or from_ark:
                self.priorities.discard(key)

            # Forward message to neighbors if not already sent
            if b not in self.messages_sent:
                heapq.heappush(self.messages_to_send, b)
                self.messages_sent.add(b)

    def _formation_move(self) -> Move:
        """Move in zigzag pattern within assigned strip."""
        # First, go to assigned strip if not there yet
        if not self.at_strip:
            # Move to top of assigned strip
            target_x = self.my_strip_start + self.strip_width / 2
            target_y = 0

            # Check if we've arrived
            if (
                abs(self.position[0] - target_x) < 0.5
                and abs(self.position[1] - target_y) < 0.5
            ):
                self.at_strip = True
                # Start at top-left corner
                return Move(*self.move_towards(self.my_strip_start, 0))

            return Move(*self.move_towards(target_x, target_y))

        # Now do zigzag within strip
        current_x = self.position[0]

        # Zigzag pattern:
        # Row 0: sweep right (start to end)
        # Row 1: sweep left (end to start)
        # Row 2: sweep right (start to end)
        # etc.

        target_row_y = self.sweep_row * self.row_height

        # Determine if we're on an even or odd row
        sweep_right = self.sweep_row % 2 == 0

        # Check if we've completed current row
        if sweep_right:
            # Sweeping right: check if reached right edge
            if current_x >= self.my_strip_end - 0.5:
                # Move to next row
                self.sweep_row += 1
                target_row_y = self.sweep_row * self.row_height

                # Check if finished entire strip
                if target_row_y >= c.Y:
                    # Reset to top
                    self.sweep_row = 0
                    return Move(*self.move_towards(self.my_strip_start, 0))

                # Move down to next row at right edge
                return Move(*self.move_towards(self.my_strip_end, target_row_y))
            else:
                # Continue sweeping right
                target_x = min(current_x + c.MAX_DISTANCE_KM, self.my_strip_end)
                return Move(*self.move_towards(target_x, target_row_y))
        else:
            # Sweeping left: check if reached left edge
            if current_x <= self.my_strip_start + 0.5:
                # Move to next row
                self.sweep_row += 1
                target_row_y = self.sweep_row * self.row_height

                # Check if finished entire strip
                if target_row_y >= c.Y:
                    # Reset to top
                    self.sweep_row = 0
                    return Move(*self.move_towards(self.my_strip_end, 0))

                # Move down to next row at left edge
                return Move(*self.move_towards(self.my_strip_start, target_row_y))
            else:
                # Continue sweeping left
                target_x = max(current_x - c.MAX_DISTANCE_KM, self.my_strip_start)
                return Move(*self.move_towards(target_x, target_row_y))
