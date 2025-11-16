import pygame
from typing import Callable
from collections import deque

from core.animal import Animal, Gender
from core.ark import Ark
from core.cell import Cell
from core.engine import Engine
from core.player_info import PlayerInfo
from core.ui.utils import render_img, write_at
from core.views.player_view import Kind

import core.constants as c


def km_to_px(km: float) -> float:
    diff = c.Y // c.MAP_SPLIT
    return c.LANDSCAPE_HEIGHT * km / diff


def is_hovered_circle(
    mouse_pos: tuple[int, int], center: tuple[float, float], radius: float
) -> bool:
    mx, my = mouse_pos
    cx, cy = center
    return (mx - cx) ** 2 + (my - cy) ** 2 <= radius**2


class ArkUI:
    def __init__(self, engine: Engine) -> None:
        pygame.init()

        self.engine = engine
        self.running = True
        self.paused = True
        self.clock = pygame.time.Clock()

        self.turn = 0

        self.screen = pygame.display.set_mode((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
        self.bg_color = c.BG_COLOR
        self.big_font = pygame.font.SysFont(None, 40)
        self.small_font = pygame.font.SysFont(None, 32)
        self.tiny_font = pygame.font.SysFont(None, 28)

        self.debug_mode = False

        self.drawn_objects: dict[
            tuple[tuple[float, float], float], Ark | PlayerInfo | Animal
        ] = {}

        self.drawn_cells: dict[tuple[tuple[int, int], int], tuple[int, int]] = {}

        self.selected_cell = (
            self.engine.ark.position[0] // (c.X // c.MAP_SPLIT),
            self.engine.ark.position[1] // (c.Y // c.MAP_SPLIT),
        )

        self.hz = c.DEFAULT_TURNS_PER_SECOND
        self.hzs = c.ALL_TURNS_PER_SECOND

        self.scrolls: list[Callable[[int, int, int], None]] = []
        self.scroll_deltas: dict[str, int] = {}

        # tracks the time the past x turns have taken
        self.times = deque(maxlen=50)

    def coords_fit_in_grid(self, x: float, y: float) -> bool:
        west_x, east_x, north_y, south_y = self.get_w_e_n_s()

        return west_x <= x <= east_x and north_y <= y <= south_y

    def map_coords_to_px(self, x: float, y: float) -> tuple[int, int]:
        west_px, east_px, north_px, south_px = self.get_map_px_w_e_n_s()

        x_px = west_px + (east_px - west_px) * x / c.X
        y_px = north_px + (south_px - north_px) * y / c.Y
        return int(x_px), int(y_px)

    def coords_to_px(self, x: float, y: float) -> tuple[int, int]:
        if not self.coords_fit_in_grid(x, y):
            raise Exception(f"tried getting px for coords not in grid: {x, y}")

        west_x, east_x, north_y, south_y = self.get_w_e_n_s()

        rel_x = x - west_x
        rel_y = y - north_y

        diff_x = east_x - west_x
        diff_y = south_y - north_y

        x_px = (
            c.LANDSCAPE_WEST_PX
            + (c.LANDSCAPE_EAST_PX - c.LANDSCAPE_WEST_PX) * rel_x / diff_x
        )
        y_px = (
            c.LANDSCAPE_NORTH_PX
            + (c.LANDSCAPE_SOUTH_PX - c.LANDSCAPE_NORTH_PX) * rel_y / diff_y
        )
        return int(x_px), int(y_px)

    def get_map_px_w_e_n_s(self) -> tuple[int, int, int, int]:
        west_px = c.LANDSCAPE_WIDTH + int(
            ((c.SCREEN_WIDTH + c.MARGIN_X - c.LANDSCAPE_WIDTH) - c.MAP_PX) / 2
        )
        north_px = c.SCREEN_HEIGHT - c.MAP_PX - c.MARGIN_Y
        east_px = west_px + c.MAP_PX
        south_px = north_px + c.MAP_PX

        return west_px, east_px, north_px, south_px

    def draw_map(self):
        west_px, east_px, north_px, south_px = self.get_map_px_w_e_n_s()

        # border_rect = pygame.Rect(west_px, north_px, c.MAP_PX, c.MAP_PX)
        # pygame.draw.rect(self.screen, color, border_rect)  # fill
        # pygame.draw.rect(self.screen, (0, 0, 0), border_rect, 2)  # border

        for row in range(c.MAP_SPLIT):
            for col in range(c.MAP_SPLIT):
                cell_west = west_px + int((east_px - west_px) * col / c.MAP_SPLIT)
                cell_north = north_px + int((south_px - north_px) * row / c.MAP_SPLIT)

                dim = int(c.MAP_PX / c.MAP_SPLIT)
                rect = pygame.Rect(cell_west, cell_north, dim, dim)

                color = (
                    c.DAMP_GRASS_COLOR if self.engine.is_raining() else c.GRASS_COLOR
                )
                if (col, row) == self.selected_cell:
                    r, g, b = color
                    color = (
                        min(int(r * c.SELECTED_INCREASE), 255),
                        min(int(g * c.SELECTED_INCREASE), 255),
                        min(int(b * c.SELECTED_INCREASE), 255),
                    )

                pygame.draw.rect(self.screen, color, rect)
                pygame.draw.rect(self.screen, (0, 0, 0), rect, 1)

                self.drawn_cells[((cell_west, cell_north), dim)] = (col, row)

            # line = "X"
            # if i:
            #     val = c.X * i / c.MAP_SPLIT
            #     line = f"{int(val)}" if val.is_integer() else f"{val:.1f}"
            # write_at(self.screen, self.tiny_font, line, (x, c.MARGIN_Y - 20))

        self.draw_ark_on_map()
        self.draw_animals_on_map()
        self.draw_helpers_on_map()

    def get_w_e_n_s(self) -> tuple[int, int, int, int]:
        west_x, north_y = self.selected_cell
        east_x, south_y = west_x + 1, north_y + 1

        west_x *= c.X // c.MAP_SPLIT
        north_y *= c.Y // c.MAP_SPLIT
        east_x *= c.X // c.MAP_SPLIT
        south_y *= c.Y // c.MAP_SPLIT

        return west_x, east_x, north_y, south_y

    def draw_grid(self):
        """Draw garden boundaries and grid."""
        border_rect = pygame.Rect(
            c.MARGIN_X, c.MARGIN_Y, c.LANDSCAPE_WIDTH, c.LANDSCAPE_HEIGHT
        )
        color = c.DAMP_GRASS_COLOR if self.engine.is_raining() else c.GRASS_COLOR
        pygame.draw.rect(self.screen, color, border_rect)  # fill
        pygame.draw.rect(self.screen, (0, 0, 0), border_rect, 2)  # border

        west_x, east_x, north_y, south_y = self.get_w_e_n_s()

        for i in range(c.NUM_GRID_LINES + 1):
            x = c.MARGIN_X + int(c.LANDSCAPE_WIDTH * i / c.NUM_GRID_LINES)

            if i not in [0, c.NUM_GRID_LINES]:
                # only draw lines inside the grid
                pygame.draw.line(
                    self.screen,
                    c.GRIDLINE_COLOR,
                    (x, c.MARGIN_Y),
                    (x, c.MARGIN_Y + c.LANDSCAPE_HEIGHT),
                )

            line = "X"
            if i:
                val = west_x + (east_x - west_x) * i / c.NUM_GRID_LINES
                line = f"{int(val)}" if val.is_integer() else f"{val:.1f}"
            write_at(self.screen, self.tiny_font, line, (x, c.MARGIN_Y - 20))

        for i in range(c.NUM_GRID_LINES + 1):
            y = c.MARGIN_Y + int(c.LANDSCAPE_HEIGHT * i / c.NUM_GRID_LINES)

            if i not in [0, c.NUM_GRID_LINES]:
                pygame.draw.line(
                    self.screen,
                    c.GRIDLINE_COLOR,
                    (c.MARGIN_X, y),
                    (c.MARGIN_X + c.LANDSCAPE_WIDTH, y),
                )

            line = "Y"
            if i:
                val = north_y + (south_y - north_y) * i / c.NUM_GRID_LINES
                line = f"{int(val)}" if val.is_integer() else f"{val:.1f}"
            write_at(
                self.screen, self.tiny_font, line, (c.MARGIN_X - 10, y), align="right"
            )

    def draw_ark_on_map(self):
        ark_x, ark_y = self.engine.ark.position
        ark_center = self.map_coords_to_px(ark_x, ark_y)
        render_img(self.screen, ark_center, "sprites/a.png", c.ARK_RADIUS)

    def draw_ark(self):
        ark_x, ark_y = self.engine.ark.position
        if not self.coords_fit_in_grid(ark_x, ark_y):
            return

        ark_center = self.coords_to_px(ark_x, ark_y)
        render_img(self.screen, ark_center, "sprites/a.png", int(2.5 * c.ARK_RADIUS))
        key = (ark_center, c.ARK_RADIUS)
        self.drawn_objects[key] = self.engine.ark

    def render_hover_view(self, title: str):
        cw = int(c.SCREEN_WIDTH / 2)
        ch = int(c.SCREEN_HEIGHT / 2)

        left = cw - int(c.HOVERED_WIDTH / 2)
        top = ch - int(c.HOVERED_HEIGHT / 2)

        rect = pygame.Rect(
            left,
            top,
            c.HOVERED_WIDTH,
            c.HOVERED_HEIGHT,
        )
        overlay = pygame.Surface(rect.size, pygame.SRCALPHA)

        pygame.draw.rect(
            overlay, (*c.BG_COLOR, 240), overlay.get_rect(), border_radius=10
        )
        self.screen.blit(overlay, rect.topleft)
        pygame.draw.rect(self.screen, (0, 0, 0), rect, width=1, border_radius=10)

        write_at(
            self.screen, self.big_font, title, (cw, ch - int(c.HOVERED_HEIGHT / 2) + 25)
        )

        return left, top

    def draw_hovered_ark(self, pos: tuple[int, int]):
        left, top = self.render_hover_view("ARK")

        margined_x = left + c.HOVERED_MARGIN_X
        write_at(
            self.screen,
            self.small_font,
            f"pos: {pos}",
            (margined_x, top + c.MARGIN_Y),
            align="left",
        )

        species_in_ark = self.engine.ark.get_species()

        y = top + c.MARGIN_Y * 2
        for idx, (sid, (has_male, has_female)) in enumerate(species_in_ark.items()):
            write_at(
                self.screen,
                self.small_font,
                f"{chr(sid + ord('a'))}: ",
                (margined_x, y),
                align="left",
            )

            side = 40
            offset = 40

            male_rect = pygame.Rect(margined_x + offset, y - int(side / 2), side, side)
            female_rect = pygame.Rect(
                margined_x + offset + 5 + side, y - int(side / 2), side, side
            )
            if has_male:
                pygame.draw.rect(self.screen, c.MALE_ANIMAL_COLOR, male_rect)
            else:
                pygame.draw.rect(self.screen, c.MALE_ANIMAL_COLOR, male_rect, 2)

            if has_female:
                pygame.draw.rect(self.screen, c.FEMALE_ANIMAL_COLOR, female_rect)
            else:
                pygame.draw.rect(self.screen, c.FEMALE_ANIMAL_COLOR, female_rect, 2)

            if idx % 2 == 0:
                margined_x += 160
            else:
                margined_x -= 160
                y += 50

    def draw_helpers_on_map(self):
        for hi in self.engine.info_helpers.keys():
            helper_center = self.map_coords_to_px(hi.x, hi.y)
            hi.draw_on_map(self.screen, helper_center)

    def draw_helpers(self):
        for hi in self.engine.info_helpers.keys():
            if not self.coords_fit_in_grid(hi.x, hi.y):
                continue

            helper_center = self.coords_to_px(hi.x, hi.y)

            hi.draw(self.screen, self.big_font, helper_center)
            self.drawn_objects[(helper_center, c.HELPER_RADIUS)] = hi

    def draw_hovered_helper(self, hi: PlayerInfo):
        left, top = self.render_hover_view(hi.get_long_name())

        y = top + c.MARGIN_Y

        margined_x = left + c.HOVERED_MARGIN_X
        write_at(
            self.screen,
            self.small_font,
            f"pos: ({hi.x:.2f}, {hi.y:.2f})",
            (margined_x, y),
            align="left",
        )

        # noah doesn't have a flock
        if hi.kind != Kind.Noah:
            y += c.MARGIN_Y
            write_at(
                self.screen,
                self.small_font,
                "Flock",
                (margined_x, y),
                align="left",
            )
            y += 30
            hi.draw_flock(self.screen, self.big_font, (margined_x + 20, y))

        y += c.MARGIN_Y

        last_msg = self.engine.last_messages[hi.id]
        if last_msg:
            hi.draw_message(self.screen, self.big_font, (margined_x, y), last_msg)

    def draw_animals_on_map(self):
        for animal, cell in self.engine.animals.items():
            animal_center = self.map_coords_to_px(cell.x, cell.y)
            animal.draw_on_map(self.screen, animal_center)

    def draw_animals(self):
        for animal, placed in self.engine.animals.items():
            match placed:
                case Cell() as cell:
                    if not self.coords_fit_in_grid(cell.x, cell.y):
                        continue
                    animal_center = self.coords_to_px(cell.x, cell.y)

                    animal.draw(self.screen, self.big_font, animal_center)
                    self.drawn_objects[(animal_center, c.ANIMAL_RADIUS)] = animal

    def draw_hovered_animal(self, sid: int, gender: Gender, pos: tuple[int, int]):
        left, top = self.render_hover_view("Animal")

        y = top + c.MARGIN_Y

        margined_x = left + c.HOVERED_MARGIN_X
        write_at(
            self.screen,
            self.small_font,
            f"pos: {pos}",
            (margined_x, y),
            align="left",
        )

        y += c.MARGIN_Y

        write_at(
            self.screen,
            self.small_font,
            f"species_id: {sid} -> {chr(sid + ord('a'))}",
            (margined_x, y),
            align="left",
        )

        y += c.MARGIN_Y

        color = c.MALE_ANIMAL_COLOR if gender == Gender.Male else c.FEMALE_ANIMAL_COLOR

        write_at(
            self.screen,
            self.small_font,
            f"{gender}",
            (margined_x, y),
            align="left",
            color=color,
        )

    def draw_if_hovered(self):
        pos = pygame.mouse.get_pos()

        best_obj = None
        smallest_radius = -1
        for (center, radius), obj in self.drawn_objects.items():
            if is_hovered_circle(pos, center, radius):
                if best_obj is None or radius < smallest_radius:
                    best_obj = obj
                    smallest_radius = radius

        match best_obj:
            case Ark(position=p):
                self.draw_hovered_ark(p)
            case PlayerInfo() as hi:
                self.draw_hovered_helper(hi)
            case Animal(species_id=sid, gender=g):
                placed = self.engine.animals[best_obj]

                match placed:
                    case Cell() as cell:
                        self.draw_hovered_animal(sid, g, (cell.x, cell.y))

    def draw_objects(self):
        self.drawn_objects.clear()
        self.draw_ark()
        self.draw_helpers()
        self.draw_animals()

    def draw_info_lines(self, x: int, y: int):
        info_pane_x = x
        info_pane_y = y

        info_lines = [
            f"{self.engine.helpers[0]}",
            f"Turn: {self.engine.time_elapsed}/{self.engine.time}",
            f"Helpers: {len(self.engine.helpers)}",
            f"Score: {self.engine.ark.get_score()}",
        ]

        y = 0
        for i, line in enumerate(info_lines):
            y = info_pane_y + i * 30
            if line:  # Skip empty debug line when not in debug mode
                write_at(
                    self.screen, self.big_font, line, (info_pane_x, y), align="left"
                )

                if line.startswith("Turn:"):
                    speed = f"speed: {1 + self.hzs.index(self.hz)}/{len(self.hzs)}"
                    write_at(
                        self.screen,
                        self.small_font,
                        speed,
                        (info_pane_x + 220, y),
                        align="left",
                    )

        if self.engine.time_elapsed == self.engine.time:
            org_score = self.engine.ark.get_score()

            deduct = not all([hi.is_in_ark() for hi in self.engine.info_helpers.keys()])
            write_at(
                self.screen,
                self.big_font,
                f" - {org_score * deduct} = {0 if deduct else org_score}",
                (info_pane_x + 99 + 14 * (len(f"{self.engine.ark.get_score()}")), y),
                align="left",
                color=(255, 0, 0) if deduct else (0, 0, 0),
            )

        return info_pane_x, y

    def draw_animals_helpers(self, x: int, y: int):
        info_pane_x = x
        y += 40
        base_y = y

        write_at(self.screen, self.big_font, "Animals", (info_pane_x, y), align="left")
        for sid, (num_male, num_female) in self.engine.species_stats.items():
            y += 30
            write_at(
                self.screen,
                self.big_font,
                f"{chr(sid + ord('a'))}:",
                (info_pane_x, y),
                align="left",
            )
            write_at(
                self.screen,
                self.big_font,
                f"{num_male}M",
                (info_pane_x + 100, y),
                align="right",
                color=c.MALE_ANIMAL_COLOR,
            )
            write_at(
                self.screen,
                self.big_font,
                f"{num_female}F",
                (info_pane_x + 180, y),
                align="right",
                color=c.FEMALE_ANIMAL_COLOR,
            )

        y = base_y
        x = info_pane_x + 185
        write_at(self.screen, self.big_font, "Helpers", (x, y), align="left")

        west, north, east, south = (
            x,
            y + 20,
            c.SCREEN_WIDTH,
            c.SCREEN_HEIGHT - c.MAP_PX - c.MARGIN_Y - 5,
        )
        helpers_box = pygame.Rect(west, north, east - west, south - north)

        helper_box_height = max(0, c.INFO_HELPER_HEIGHT * len(self.engine.helpers))

        def scroll_helpers_box(mx: int, my: int, delta: int):
            if not (west <= mx <= east and north <= my <= south):
                return

            key = scroll_helpers_box.__name__
            self.scroll_deltas[key] = max(
                0,
                min(
                    self.scroll_deltas[key] - 15 * delta,
                    helper_box_height - (south - north),
                ),
            )

        if scroll_helpers_box.__name__ not in self.scroll_deltas:
            self.scroll_deltas[scroll_helpers_box.__name__] = 0
            self.scrolls.append(scroll_helpers_box)

        helpers_surface = pygame.Surface(
            (helpers_box.w, helper_box_height), pygame.SRCALPHA
        )

        y = 10
        x = 0

        for hi in self.engine.info_helpers.keys():
            if hi.kind == Kind.Noah:
                write_at(
                    helpers_surface,
                    self.big_font,
                    f"{hi.get_short_name()}: no flock",
                    (x, y),
                    align="left",
                )
            else:
                write_at(
                    helpers_surface,
                    self.big_font,
                    f"{hi.get_short_name()}: ",
                    (x, y),
                    align="left",
                )
                hi.draw_flock(helpers_surface, self.big_font, (x + 60, y))

            incr_y = y + c.INFO_HELPER_HEIGHT // 2

            msg = self.engine.last_messages[hi.id]
            if msg:
                hi.draw_message(helpers_surface, self.small_font, (x, incr_y), msg)
            else:
                write_at(
                    helpers_surface,
                    self.small_font,
                    "no msg",
                    (x, incr_y),
                    align="left",
                )

            y += c.INFO_HELPER_HEIGHT

        # pygame.draw.rect(self.screen, (0, 0, 0), helpers_box, 1)
        self.screen.set_clip(helpers_box)
        self.screen.blit(
            helpers_surface,
            (
                helpers_box.x,
                helpers_box.y - self.scroll_deltas[scroll_helpers_box.__name__],
            ),
        )
        self.screen.set_clip(None)

    def draw_raindrop(self):
        x, y = c.SCREEN_WIDTH - c.MARGIN_X, c.MARGIN_Y
        if self.engine.is_raining():
            render_img(self.screen, (x, y), "sprites/rd.png", 60)

    def draw_info_panel(self):
        info_pane_x = c.LANDSCAPE_EAST_PX + 30
        info_pane_y = c.MARGIN_Y - 10

        x, y = self.draw_info_lines(info_pane_x, info_pane_y)
        self.draw_animals_helpers(x, y)
        self.draw_raindrop()
        tps = 1 / (sum(self.times) / len(self.times)) if len(self.times) else 0
        write_at(
            self.screen,
            self.tiny_font,
            f"tps: {tps:.1f}",
            (c.SCREEN_WIDTH - c.MARGIN_X, c.SCREEN_HEIGHT - c.MARGIN_Y + 10),
            align="right",
        )

    def draw_debug_helper_screens(self):
        grid = pygame.Rect(
            c.MARGIN_X, c.MARGIN_Y, c.LANDSCAPE_WIDTH, c.LANDSCAPE_HEIGHT
        )

        mask = pygame.Surface((grid.w, grid.h), pygame.SRCALPHA)
        mask.fill((0, 0, 0, 50))

        for hi in self.engine.info_helpers.keys():
            if not self.coords_fit_in_grid(hi.x, hi.y):
                continue

            grid_center = self.coords_to_px(hi.x, hi.y)
            center = grid_center[0] - grid.x, grid_center[1] - grid.y
            radius = km_to_px(c.MAX_SIGHT_KM)

            pygame.draw.circle(mask, (0, 0, 0, 0), center, radius)

        for hi in self.engine.info_helpers.keys():
            if not self.coords_fit_in_grid(hi.x, hi.y):
                continue

            grid_center = self.coords_to_px(hi.x, hi.y)
            center = grid_center[0] - grid.x, grid_center[1] - grid.y
            radius = km_to_px(c.MAX_SIGHT_KM)

            pygame.draw.circle(mask, (0, 0, 0, 255), center, radius, width=1)

        self.screen.blit(mask, grid.topleft)

    def draw_debug_info(self):
        if not self.debug_mode:
            return

        self.draw_debug_helper_screens()

    def step_simulation(self):
        """Run one turn of simulation."""
        if self.engine.time_elapsed < self.engine.time:
            took = self.engine.run_turn()
            self.times.append(took)
            self.turn += 1
        else:
            self.paused = True

    def handle_events(self):
        """Handle pygame events."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (
                event.type == pygame.KEYDOWN and event.key == pygame.K_q
            ):
                self.running = False

            # left mouse click
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                x, y = event.pos

                for cell, val in self.drawn_cells.items():
                    (w, n), d = cell
                    map_x, map_y = val

                    if w <= x <= w + d and n <= y <= n + d:
                        self.selected_cell = (map_x, map_y)

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_SPACE:
                    self.paused = not self.paused
                elif event.key == pygame.K_d:
                    self.debug_mode = not self.debug_mode

                elif event.key == pygame.K_RIGHT:
                    sel_row, sel_col = self.selected_cell
                    self.selected_cell = ((sel_row + 1) % c.MAP_SPLIT, sel_col)
                elif event.key == pygame.K_LEFT:
                    sel_row, sel_col = self.selected_cell
                    self.selected_cell = ((sel_row - 1) % c.MAP_SPLIT, sel_col)
                elif event.key == pygame.K_DOWN:
                    sel_row, sel_col = self.selected_cell
                    self.selected_cell = (sel_row, (sel_col + 1) % c.MAP_SPLIT)
                elif event.key == pygame.K_UP:
                    sel_row, sel_col = self.selected_cell
                    self.selected_cell = (sel_row, (sel_col - 1) % c.MAP_SPLIT)

                elif event.key == pygame.K_1:
                    self.hz = self.hzs[0]
                elif event.key == pygame.K_2:
                    self.hz = self.hzs[1]
                elif event.key == pygame.K_3:
                    self.hz = self.hzs[2]

            elif pygame.key.get_pressed()[pygame.K_PERIOD] and self.paused:
                self.step_simulation()

            # scroll
            elif event.type == pygame.MOUSEWHEEL:
                delta = event.y
                x, y = pygame.mouse.get_pos()
                [handle_scroll(x, y, delta) for handle_scroll in self.scrolls]

    def run(self):
        while self.running:
            self.screen.fill(self.bg_color)
            self.draw_grid()
            self.draw_objects()
            self.draw_info_panel()
            self.draw_map()
            self.draw_debug_info()
            self.draw_if_hovered()

            self.handle_events()

            if not self.paused:
                self.step_simulation()
                self.clock.tick(self.hz)

            pygame.display.flip()
            self.clock.tick(max(self.hzs))

        pygame.quit()

        return self.engine.get_results()
