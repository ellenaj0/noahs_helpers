from core.action import Action
from core.message import Message
from core.player import Player
from core.snapshots import HelperSurroundingsSnapshot
from core.views.player_view import Kind


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

    def check_surroundings(self, snapshot: HelperSurroundingsSnapshot) -> int:
        return 0

    def get_action(self, messages: list[Message]) -> Action | None:
        return None
