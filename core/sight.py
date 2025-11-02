from typing import Iterator

from core.cell import Cell, CellView

import core.constants as c


def _create_cellview_at(
    target_x: int, target_y: int, helper_x: int, helper_y: int, grid: list[list[Cell]]
) -> CellView:
    # if the target cell is the same as the helper's cell
    # animal genders should not be unknown
    return grid[target_y][target_x].get_view(
        make_unknown=not (helper_x == target_x and helper_y == target_y)
    )


class Sight:
    def __init__(self, position: tuple[float, float], grid: list[list[Cell]]) -> None:
        self.helper_x_real, self.helper_y_real = position
        self.helper_x_int, self.helper_y_int = (
            int(self.helper_x_real),
            int(self.helper_y_real),
        )

        self.west = max(self.helper_x_int - c.MAX_SIGHT_KM, 0)
        self.east = min(self.helper_x_int + c.MAX_SIGHT_KM, c.X - 1)
        self.north = max(self.helper_y_int - c.MAX_SIGHT_KM, 0)
        self.south = min(self.helper_y_int + c.MAX_SIGHT_KM, c.Y - 1)

        self._sight: list[list[CellView | None]] = [
            [None for _ in range(self.west, self.east + 1)]
            for _ in range(self.north, self.south + 1)
        ]

        for y in range(self.north, self.south + 1):
            for x in range(self.west, self.east + 1):
                if self.cell_is_in_sight(x, y):
                    self._sight[y - self.north][x - self.west] = _create_cellview_at(
                        x, y, self.helper_x_int, self.helper_y_int, grid
                    )

    def cell_is_in_sight(self, x: int, y: int) -> bool:
        if not (self.west <= x <= self.east and self.north <= y <= self.south):
            return False

        if self.helper_x_real < x:
            dx = x - self.helper_x_real
        elif x - self.helper_x_real <= 1:
            dx = 0
        else:
            dx = self.helper_x_real - x - 1

        if self.helper_y_real < y:
            dy = y - self.helper_y_real
        elif y - self.helper_y_real <= 1:
            dy = 0
        else:
            dy = self.helper_y_real - y - 1

        return (dy**2 + dx**2) ** 0.5 <= c.MAX_SIGHT_KM

    def get_cellview_at(self, x: int, y: int) -> CellView:
        """Before calling, ensure cell is in sight using `self.cell_is_in_sight`."""
        if not (self.west <= x <= self.east and self.north <= y <= self.south):
            raise Exception(f"coordinate {(x, y)} is not in player sight")

        cell = self._sight[y - self.north][x - self.west]

        if cell is None:
            raise Exception(f"coordinate {(x, y)} is not in player sight")

        return cell

    def __iter__(self) -> Iterator[CellView | None]:
        for y in range(self.north, self.south + 1):
            for x in range(self.west, self.east + 1):
                yield self._sight[y][x]
