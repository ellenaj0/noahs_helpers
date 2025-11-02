from core.action import Action, Move
from core.message import Message
from core.player import Player
from core.snapshots import HelperSurroundingsSnapshot


class RandomPlayer(Player):
    def __init__(self, id: int, ark_x: int, ark_y: int):
        super().__init__(id, ark_x, ark_y)
        print(f"I am {self}")

    def run(self) -> None:
        pass

    def check_surroundings(self, snapshot: HelperSurroundingsSnapshot):
        print(f"{self.id}: checking surroundings.. pos={snapshot.position}")

        msg = snapshot.time_elapsed + self.id
        if not self.is_message_valid(msg):
            msg = msg & 0xFF

        return msg

    def get_action(self, messages: list[Message]) -> Action:
        for msg in messages:
            print(f"{self.id}: got {msg.contents} from {msg.from_helper.id}")

        return Move(*self.position)
