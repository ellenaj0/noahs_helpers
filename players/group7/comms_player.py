from core.action import Action, Move, Obtain, Release
from core.message import Message
from core.player import Player
from core.snapshots import HelperSurroundingsSnapshot
from core.views.player_view import Kind
from core.views.cell_view import CellView
from random import random, choice
import heapq

# Bit definitions for 1-byte messages
LOCAL_BIT = 0b00000001  # bit 0, message originated from helper
ARK_BIT = 0b00000010  # bit 1, message originated from ark
GENDER_BIT = 0b00000100  # bit 2
SPECIES_BITS = 0b11111000  # bits 3-7 for species ID


def encode_message(species_id: int, gender: int, from_ark: bool) -> int:
    msg = (species_id << 3) | (gender << 2)
    if from_ark:
        msg |= ARK_BIT  # set the ARK_BIT if message comes from the ark
    else:
        msg |= LOCAL_BIT  # set the LOCAL_BIT if message comes from a helper
    return msg & 0xFF  # ensure it fits in one byte


def decode_message(msg_int: int):
    from_ark = bool(msg_int & ARK_BIT)  # check if ARK_BIT is set
    from_local = bool(msg_int & LOCAL_BIT)  # check if LOCAL_BIT is set
    gender = (msg_int & GENDER_BIT) >> 2  # extract gender from bit 2
    species_id = (msg_int & SPECIES_BITS) >> 3  # extract species ID from bits 3-7
    return species_id, gender, from_ark, from_local


def distance(x1: float, y1: float, x2: float, y2: float) -> float:
    return ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5


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

        self.priorities: set[tuple[int, int]] = set()  # (species_id, gender)
        self.messages_received: dict[int, int] = dict()  # sender_id -> message
        self.messages_sent: set[int] = set()  # track messages already sent
        self.messages_to_send: list[int] = []  # messages queued for sending
        self.last_seen_ark_animals: set[tuple[int, int]] = (
            set()
        )  # track last seen ark animals
        self.first_turn_done: bool = False  # flag to handle turn-0 initialization

    def _get_random_move(self) -> tuple[float, float]:
        old_x, old_y = self.position
        dx, dy = random() - 0.5, random() - 0.5

        while not (self.can_move_to(old_x + dx, old_y + dy)):
            dx, dy = random() - 0.5, random() - 0.5

        return old_x + dx, old_y + dy

    def _get_my_cell(self) -> CellView:
        xcell, ycell = tuple(map(int, self.position))
        if not self.sight.cell_is_in_sight(xcell, ycell):
            raise Exception(f"{self} failed to find own cell")
        return self.sight.get_cellview_at(xcell, ycell)

    def _find_closest_priority_animal(self):
        closest_animal_pos = None
        closest_dist = float("inf")
        for cellview in self.sight:
            priority_animals = [
                a
                for a in cellview.animals
                if (a.species_id, a.gender.value) in self.priorities
            ]
            if priority_animals:
                dist = distance(*self.position, cellview.x, cellview.y)
                if dist < closest_dist:
                    closest_dist = dist
                    closest_animal_pos = (cellview.x, cellview.y)
        return closest_animal_pos

    def check_surroundings(self, snapshot: HelperSurroundingsSnapshot) -> int:
        # Update internal state
        self.position = snapshot.position
        self.flock = snapshot.flock
        self.sight = snapshot.sight
        self.is_raining = snapshot.is_raining

        # turn 0: initialize priorities for helpers
        if not self.first_turn_done and self.kind != Kind.Noah:
            for species_id, count in enumerate(self.species_populations.values()):
                # assume at least one male and one female per species
                self.priorities.add((species_id, 0))
                self.priorities.add((species_id, 1))
            self.first_turn_done = True

        # noah messages. nothing rn
        if self.kind == Kind.Noah:
            if self.messages_to_send:
                return heapq.heappop(self.messages_to_send)
            return 0

        # helpers: process ark view for remove/release messages
        if snapshot.ark_view:
            current_ark_animals = {
                (a.species_id, a.gender.value) for a in snapshot.ark_view.animals
            }

            # identify new animals in the ark (that we need to release locally)
            new_animals = current_ark_animals - self.last_seen_ark_animals
            for species_id, gender in new_animals:
                if (species_id, gender) in self.priorities:
                    self.priorities.remove((species_id, gender))
                    # ark-originated message triggers release
                    remove_msg = encode_message(species_id, gender, from_ark=True)
                    if remove_msg not in self.messages_sent:
                        heapq.heappush(self.messages_to_send, remove_msg)
                        self.messages_sent.add(remove_msg)

            # update last_seen_ark_animals for next turn diffing
            self.last_seen_ark_animals = current_ark_animals

        # send next message in queue, if any
        if self.messages_to_send:
            return heapq.heappop(self.messages_to_send)

        return 0

    def get_action(self, messages: list[Message]) -> Action | None:
        # process incoming messages
        for msg in messages:
            species_id, gender, from_ark, from_local = decode_message(msg.contents)
            key = (species_id, gender)

            if from_ark:
                # release animal if you have it
                for a in self.flock:
                    if (a.species_id, a.gender.value) == key:
                        return Release(a)
            elif from_local:
                # update priorities only
                self.priorities.discard(key)

            # gather neighbors
            neighbor_ids = {
                helper_info.id
                for cell in self.sight
                for helper_info in cell.helpers
                if helper_info.id != self.id
            }

            # forward message if not already sent and neighbor exists besides sender
            if msg.contents not in self.messages_sent and any(
                n != msg.from_helper.id for n in neighbor_ids
            ):
                heapq.heappush(self.messages_to_send, msg.contents)
                self.messages_sent.add(msg.contents)

            # record message as received
            self.messages_received[msg.from_helper.id] = msg.contents

        # Noah does not move or act
        if self.kind == Kind.Noah:
            return None

        # move to ark if raining or flock full
        if self.is_raining or len(self.flock) >= 4:
            if tuple(map(int, self.position)) != self.ark_position:
                return Move(*self.move_towards(*self.ark_position))

        # obtain priority animals in current cell first
        cellview = self._get_my_cell()
        priority_animals = [
            a
            for a in cellview.animals
            if (a.species_id, a.gender.value) in self.priorities
        ]
        if priority_animals:
            chosen = choice(priority_animals)
            self.priorities.remove((chosen.species_id, chosen.gender.value))
            # broadcast helper-to-helper message (LOCAL_BIT)
            remove_msg = encode_message(
                chosen.species_id, chosen.gender.value, from_ark=False
            )
            heapq.heappush(self.messages_to_send, remove_msg)
            return Obtain(chosen)

        # move toward closest priority animal
        closest = self._find_closest_priority_animal()
        if closest:
            return Move(*self.move_towards(*closest))

        # otherwise, proceed in set pattern
        return Move(*self._get_random_move())
