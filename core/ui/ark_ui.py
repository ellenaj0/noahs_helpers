import pygame

from core.animal import Animal, Gender
from core.ark import Ark
from core.engine import Engine
from core.player import Player
from core.ui.utils import write_at
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
            tuple[tuple[float, float], float], Ark | Player | Animal
        ] = {}

        self.drawn_cells: dict[tuple[tuple[int, int], int], tuple[int, int]] = {}

        self.selected_cell = (
            self.engine.ark.position[0] // (c.X // c.MAP_SPLIT),
            self.engine.ark.position[1] // (c.Y // c.MAP_SPLIT),
        )

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

        ark_img_orig = pygame.image.load("sprites/ark.png").convert_alpha()
        ark_img = pygame.transform.scale(ark_img_orig, (c.ARK_RADIUS, c.ARK_RADIUS))
        ark_rect = ark_img.get_rect(center=ark_center)
        self.screen.blit(ark_img, ark_rect)

    def draw_ark(self):
        ark_x, ark_y = self.engine.ark.position
        if not self.coords_fit_in_grid(ark_x, ark_y):
            return

        ark_center = self.coords_to_px(ark_x, ark_y)

        ark_img_orig = pygame.image.load("sprites/ark.png").convert_alpha()
        ark_img = pygame.transform.scale(
            ark_img_orig, (2.5 * c.ARK_RADIUS, 2.5 * c.ARK_RADIUS)
        )
        ark_rect = ark_img.get_rect(center=ark_center)
        self.screen.blit(ark_img, ark_rect)

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
        for sid, (has_male, has_female) in species_in_ark.items():
            write_at(
                self.screen, self.small_font, f"{sid}: ", (margined_x, y), align="left"
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

            y += 50

    def draw_helpers_on_map(self):
        for helper in self.engine.helpers:
            helper_x, helper_y = helper.position

            helper_center = self.map_coords_to_px(helper_x, helper_y)
            helper.draw_on_map(self.screen, helper_center)

    def draw_helpers(self):
        for helper in self.engine.helpers:
            helper_x, helper_y = helper.position
            if not self.coords_fit_in_grid(helper_x, helper_y):
                continue

            helper_center = self.coords_to_px(helper_x, helper_y)

            helper.draw(self.screen, self.big_font, helper_center)
            self.drawn_objects[(helper_center, c.HELPER_RADIUS)] = helper

    def draw_hovered_helper(self, helper: Player):
        left, top = self.render_hover_view(helper.get_long_name())

        y = top + c.MARGIN_Y

        margined_x = left + c.HOVERED_MARGIN_X
        write_at(
            self.screen,
            self.small_font,
            f"pos: ({helper.position[0]:.2f}, {helper.position[1]:.2f})",
            (margined_x, y),
            align="left",
        )

        # noah doesn't have a flock
        if helper.kind != Kind.Noah:
            y += c.MARGIN_Y
            write_at(
                self.screen,
                self.small_font,
                "Flock",
                (margined_x, y),
                align="left",
            )
            y += 30
            helper.draw_flock(self.screen, self.big_font, (margined_x + 20, y))

        y += c.MARGIN_Y

        last_msg = self.engine.last_messages[helper.id]
        if last_msg is not None:
            write_at(
                self.screen,
                self.small_font,
                f"Last msg: 0b{last_msg:08b}={last_msg}",
                (margined_x, y),
                align="left",
            )

    def draw_animals_on_map(self):
        for animal, cell in self.engine.free_animals.items():
            animal_center = self.map_coords_to_px(cell.x, cell.y)
            animal.draw_on_map(self.screen, animal_center)

    def draw_animals(self):
        for animal, cell in self.engine.free_animals.items():
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
            f"species_id: {sid}",
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
            case Player() as player:
                self.draw_hovered_helper(player)
            case Animal(species_id=sid, gender=g):
                cell = self.engine.free_animals[best_obj]
                self.draw_hovered_animal(sid, g, (cell.x, cell.y))

    def draw_objects(self):
        self.drawn_objects.clear()
        self.draw_ark()
        self.draw_helpers()
        self.draw_animals()

    def draw_info_panel(self):
        info_pane_x = c.LANDSCAPE_EAST_PX + 30
        info_pane_y = c.MARGIN_Y

        info_lines = [
            f"{self.engine.helpers[0]}",
            "",
            f"Turn: {self.engine.time_elapsed}/{self.engine.time}",
            f"Score: {self.engine.ark.get_score()}",
            f"Helpers: {len(self.engine.helpers)}",
            f"is_raining: {self.engine.is_raining()}",
            f"{'DEBUG ON' if self.debug_mode else 'DEBUG OFF'}",  # NEW: Show debug status
        ]

        y = 0
        for i, line in enumerate(info_lines):
            y = info_pane_y + i * 30
            if line:  # Skip empty debug line when not in debug mode
                write_at(
                    self.screen, self.big_font, line, (info_pane_x, y), align="left"
                )

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
        x = info_pane_x + 190
        write_at(self.screen, self.big_font, "Helpers", (x, y), align="left")
        for helper in self.engine.helpers:
            if helper.kind == Kind.Noah:
                continue
            y += 30
            write_at(
                self.screen,
                self.big_font,
                f"{helper.get_short_name()}: ",
                (x, y),
                align="left",
            )
            helper.draw_flock(self.screen, self.big_font, (x + 60, y))

    def draw_debug_helper_screens(self):
        grid = pygame.Rect(
            c.MARGIN_X, c.MARGIN_Y, c.LANDSCAPE_WIDTH, c.LANDSCAPE_HEIGHT
        )

        mask = pygame.Surface((grid.w, grid.h), pygame.SRCALPHA)
        mask.fill((0, 0, 0, 50))

        for helper in self.engine.helpers:
            if not self.coords_fit_in_grid(*helper.position):
                continue

            grid_center = self.coords_to_px(*helper.position)
            center = grid_center[0] - grid.x, grid_center[1] - grid.y
            radius = km_to_px(c.MAX_SIGHT_KM)

            pygame.draw.circle(mask, (0, 0, 0, 0), center, radius)

        for helper in self.engine.helpers:
            if not self.coords_fit_in_grid(*helper.position):
                continue

            grid_center = self.coords_to_px(*helper.position)
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
            self.engine.run_turn()
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
                elif event.key == pygame.K_d:  # NEW: Toggle debug mode
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

            elif pygame.key.get_pressed()[pygame.K_PERIOD] and self.paused:
                self.step_simulation()

    def run(self) -> float:
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

            pygame.display.flip()
            self.clock.tick(60)

        pygame.quit()

        return self.engine.ark.get_score()
