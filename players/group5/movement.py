"""Movement strategies for Player5."""
import math
from random import random
from typing import Tuple, Optional
import core.constants as c
from core.action import Move
from .constants import (
    TARGET_POINT_DISTANCE,
    BACKTRACK_MIN_ANGLE,
    BACKTRACK_MAX_ANGLE,
    NEAR_ARK_DISTANCE,
    MIN_MAP_COORD,
    MAX_MAP_COORD,
)


def get_distance(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Calculate Euclidean distance between two points."""
    return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)


def is_within_map_bounds(x: float, y: float) -> bool:
    """Check if coordinates are within map boundaries."""
    return MIN_MAP_COORD <= x <= MAX_MAP_COORD and MIN_MAP_COORD <= y <= MAX_MAP_COORD


def is_within_safe_radius(pos: Tuple[float, float], ark_pos: Tuple[float, float], safe_radius: float) -> bool:
    """Check if position is within safe radius from ark."""
    return get_distance(pos, ark_pos) <= safe_radius


def get_move_to_target(
    current_pos: Tuple[float, float], target_pos: Tuple[float, float]
) -> Move:
    """Calculate a 1km move towards the target."""
    dx = target_pos[0] - current_pos[0]
    dy = target_pos[1] - current_pos[1]
    dist = get_distance(current_pos, target_pos)

    if dist < c.EPS:
        return Move(x=target_pos[0], y=target_pos[1])

    move_dist = min(dist, c.MAX_DISTANCE_KM)
    new_x = current_pos[0] + (dx / dist) * move_dist
    new_y = current_pos[1] + (dy / dist) * move_dist

    return Move(x=new_x, y=new_y)


def get_new_random_target(
    current_pos: Tuple[float, float],
    previous_position: Tuple[float, float],
    ark_pos: Tuple[float, float],
    safe_radius: float,
    current_target_pos: Optional[Tuple[float, float]]
) -> Tuple[Move, Optional[Tuple[float, float]]]:
    """
    Pick a new 150km exploration point avoiding backtracking.

    Returns: (Move, new_current_target_pos)
    """
    current_x, current_y = current_pos
    prev_x, prev_y = previous_position

    prev_dx = current_x - prev_x
    prev_dy = current_y - prev_y

    for _ in range(150):
        angle = random() * 2 * math.pi
        target_x = current_x + math.cos(angle) * TARGET_POINT_DISTANCE
        target_y = current_y + math.sin(angle) * TARGET_POINT_DISTANCE
        target_pos = (target_x, target_y)

        # Validate target position
        if not is_within_safe_radius(target_pos, ark_pos, safe_radius):
            continue

        if not is_within_map_bounds(target_x, target_y):
            continue

        # Check backtracking angle
        new_dx = target_x - current_x
        new_dy = target_y - current_y
        mag_prev = math.sqrt(prev_dx**2 + prev_dy**2)
        mag_new = math.sqrt(new_dx**2 + new_dy**2)

        if mag_prev < c.EPS or mag_new < c.EPS:
            return get_move_to_target(current_pos, target_pos), target_pos

        dot_product = prev_dx * new_dx + prev_dy * new_dy
        cos_angle = max(-1.0, min(1.0, dot_product / (mag_prev * mag_new)))
        angle_diff = math.acos(cos_angle)

        if not (BACKTRACK_MIN_ANGLE <= angle_diff <= BACKTRACK_MAX_ANGLE):
            return get_move_to_target(current_pos, target_pos), target_pos

    # Fallback to current target or small random move
    if current_target_pos:
        return get_move_to_target(current_pos, current_target_pos), current_target_pos

    return Move(x=current_x + random() - 0.5, y=current_y + random() - 0.5), current_target_pos


def get_return_move(
    current_pos: Tuple[float, float],
    ark_pos: Tuple[float, float],
    helper_id: int,
    direct: bool = False
) -> Tuple[Move, Tuple[float, float]]:
    """
    Calculate move to return to ark.

    Args:
        current_pos: Current position
        ark_pos: Ark position
        helper_id: Helper ID for spiral direction
        direct: If True, go straight to ark. If False, spiral to explore.

    Returns: (Move, new_current_target_pos)
    """
    current_dist_to_ark = get_distance(current_pos, ark_pos)

    # Direct path when close or direct flag set
    if direct or current_dist_to_ark <= NEAR_ARK_DISTANCE:
        return get_move_to_target(current_pos, ark_pos), ark_pos

    # Spiral approach for exploration
    dx = current_pos[0] - ark_pos[0]
    dy = current_pos[1] - ark_pos[1]
    current_angle = math.atan2(dy, dx)

    arc_offset = math.radians(30) * (1 if helper_id % 2 == 0 else -1)
    spiral_angle = current_angle + arc_offset

    target_dist = current_dist_to_ark * 0.9
    target_x = ark_pos[0] + math.cos(spiral_angle) * target_dist
    target_y = ark_pos[1] + math.sin(spiral_angle) * target_dist

    target_x = max(MIN_MAP_COORD, min(MAX_MAP_COORD, target_x))
    target_y = max(MIN_MAP_COORD, min(MAX_MAP_COORD, target_y))

    new_target_pos = (target_x, target_y)
    return get_move_to_target(current_pos, new_target_pos), new_target_pos
