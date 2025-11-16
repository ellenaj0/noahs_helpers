import random
import argparse
from typing import cast, Protocol
import os
from time import time
import pathlib

from core.args import PLAYERS, Args, MapArgs
from core.player import Player
from players.random_player import RandomPlayer

import core.constants as c


class ParsedNS(Protocol):
    player: str
    seed: str | None
    gui: bool
    num_helpers: int
    animals: list[str] | None
    T: int
    ark: tuple[str, str] | None
    map_path: str | None


def sanitize_seed(org_seed: None | str) -> int:
    if org_seed is None:
        seed = int(time() * 10_000) % 100_000
        print(f"Generated seed: {seed}")
        return seed

    return int(org_seed)


def sanitize_player(org_player: None | str) -> type[Player]:
    if org_player is None:
        print("Using random player")
        return RandomPlayer

    if org_player not in PLAYERS:
        raise Exception(
            f"player `{org_player}` not valid (expected {' '.join(PLAYERS.keys())})"
        )

    return PLAYERS[org_player]


def sanitize_num_helpers(num_helpers: int | None, map_args: MapArgs | None) -> int:
    if num_helpers is None and map_args is None:
        raise Exception("did not provide num_helpers")

    if num_helpers is not None and map_args is not None:
        raise Exception("Provided `--num_helpers` flag and `--map_path`")

    if num_helpers is not None:
        if num_helpers <= 1:
            raise Exception("`--num_helpers` must be >= 2")
        return num_helpers

    if map_args is not None:
        return map_args.num_helpers

    raise Exception("unreachable")


def sanitize_animals(
    org_animals: None | list[str], map_args: MapArgs | None
) -> list[int]:
    if org_animals is None and map_args is None:
        raise Exception("Missing animal populations")

    if org_animals is not None and map_args is not None:
        raise Exception("defined both `--animals` and `--map_path")

    if org_animals is not None:
        animals = list(map(int, org_animals))
        if any([a < 2 for a in animals]):
            raise Exception("all animals must have populations >= 2")

        return animals

    if map_args is not None:
        return map_args.animals

    raise Exception("unreachable")


def sanitize_time(org_T: None | int) -> int:
    if org_T is None:
        time = random.randint(c.MIN_T, c.MAX_T)
        print(f"generated T={time}")
        return time

    if not (c.MIN_T <= org_T <= c.MAX_T):
        raise Exception(f"supplied 'T' not between {c.MIN_T} and {c.MAX_T}")

    return org_T


def sanitize_ark(
    org_ark: None | tuple[str, str], map_args: MapArgs | None
) -> tuple[int, int]:
    if org_ark is None and map_args is None:
        raise Exception("missing `--ark` and `--map_path`")
        # x, y = random.randint(0, c.X - 1), random.randint(0, c.Y - 1)
        # print(f"generated ark pos={x, y}")
        # return x, y

    if org_ark is not None and map_args is not None:
        raise Exception("defined both `--ark` and `--map_path`")

    if org_ark is not None:
        ark_x, ark_y = int(org_ark[0]), int(org_ark[1])
        if not (0 <= ark_x < c.X and 0 <= ark_y < c.Y):
            raise Exception(f"supplied ark coordinates not between 0 and {c.X}")

        return ark_x, ark_y

    if map_args is not None:
        return map_args.ark

    raise Exception("unreachable")


def get_maps_dir() -> pathlib.Path:
    return pathlib.Path(os.path.curdir + "/maps/").resolve()


def get_map(map: str | None) -> MapArgs | None:
    if map is None:
        return None

    map_dir = get_maps_dir()
    map_path = pathlib.Path(map).resolve()

    if not map_path.is_file():
        raise Exception(f'file with path "{map_path}" not found')

    try:
        map_path.relative_to(map_dir)
    except ValueError:
        raise Exception(
            'provided map path file must be inside "environments/" directory'
        )

    return MapArgs.read(map_path)


def parse_args() -> Args:
    parser = argparse.ArgumentParser(description="Run the Noah's helpers simulator.")

    parser.add_argument(
        "--player",
        choices=list(PLAYERS.keys()),
        help="Which player to run (1-10 or r for random)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="Random seed",
    )
    parser.add_argument(
        "--num_helpers",
        type=int,
        help="Number of helpers",
    )
    parser.add_argument(
        "--animals",
        nargs="+",
        metavar="S",
        help="Number of helpers",
    )
    parser.add_argument(
        "-T",
        type=int,
        help="Time, in turns",
    )

    parser.add_argument(
        "--map_path",
        help="A path to a json file (under `maps/` storing map configurations",
    )
    parser.add_argument("--gui", action="store_true", help="Enable GUI")

    parser.add_argument(
        "--ark",
        nargs=2,
        metavar=("X", "Y"),
        help="Ark position",
    )

    args = cast(ParsedNS, parser.parse_args())
    seed = sanitize_seed(args.seed)

    time = sanitize_time(args.T)
    player = sanitize_player(args.player)

    map_args = get_map(args.map_path)
    num_helpers = sanitize_num_helpers(args.num_helpers, map_args)
    animals = sanitize_animals(args.animals, map_args)
    ark = sanitize_ark(args.ark, map_args)

    return Args(
        player=player,
        seed=seed,
        gui=args.gui,
        num_helpers=num_helpers,
        animals=animals,
        time=time,
        ark=ark,
    )
