from typing import Literal
import pygame

from core.animal import Animal, Gender
from core.ark import Ark
from core.engine import Engine
import core.constants as c
from core.player import Player


def coords_to_px(x: float, y: float) -> tuple[float, float]:
    x_px = c.LANDSCAPE_WEST_PX + (c.LANDSCAPE_EAST_PX - c.LANDSCAPE_WEST_PX) * x / c.X
    y_px = (
        c.LANDSCAPE_NORTH_PX + (c.LANDSCAPE_SOUTH_PX - c.LANDSCAPE_NORTH_PX) * y / c.Y
    )
    return x_px, y_px


def km_to_px(km: float) -> float:
    return c.LANDSCAPE_HEIGHT * km / c.Y


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
        self.big_font = pygame.font.Font(None, 36)
        self.small_font = pygame.font.Font(None, 28)

        self.debug_mode = False

        self.drawn_objects: dict[
            tuple[tuple[float, float], float], Ark | Player | Animal
        ] = {}

    def write_at(
        self,
        font: pygame.font.Font,
        line: str,
        coord: tuple[int, int],
        align: Literal["left", "center", "right"] = "center",
    ):
        text = font.render(line, True, (0, 0, 0))

        # get rectangle to center the text
        match align:
            case x if x == "left":
                rect = text.get_rect()
                rect.midleft = coord
            case x if x == "center":
                rect = text.get_rect(center=coord)
            case x if x == "right":
                rect = text.get_rect()
                rect.midright = coord
            case _:
                raise Exception(f"invalid value for `align`: {align}")

        self.screen.blit(text, rect)

    def draw_grid(self):
        """Draw garden boundaries and grid."""
        border_rect = pygame.Rect(
            c.MARGIN_X, c.MARGIN_Y, c.LANDSCAPE_WIDTH, c.LANDSCAPE_HEIGHT
        )
        pygame.draw.rect(self.screen, c.GRID_COLOR, border_rect)  # fill
        pygame.draw.rect(self.screen, (0, 0, 0), border_rect, 2)  # border

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
                val = c.X * i / c.NUM_GRID_LINES
                line = f"{int(val)}" if val.is_integer() else f"{val:.1f}"
            self.write_at(self.small_font, line, (x, c.MARGIN_Y - 20))

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
                val = c.Y * i / c.NUM_GRID_LINES
                line = f"{int(val)}" if val.is_integer() else f"{val:.1f}"
            self.write_at(self.small_font, line, (c.MARGIN_X - 10, y), align="right")

    def draw_ark(self):
        ark_x, ark_y = self.engine.ark.position
        ark_center = coords_to_px(ark_x, ark_y)

        pygame.draw.circle(self.screen, c.ARK_COLOR, ark_center, c.ARK_RADIUS)

        key = (ark_center, c.ARK_RADIUS)
        self.drawn_objects[key] = self.engine.ark

    def draw_hovered_ark(self, pos: tuple[int, int], animals: set[Animal]):
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

        pygame.draw.rect(self.screen, c.BG_COLOR, rect)
        self.write_at(self.big_font, "ARK", (cw, ch - int(c.HOVERED_HEIGHT / 2) + 15))

        margined_x = left + c.HOVERED_MARGIN_X
        self.write_at(
            self.small_font,
            f"pos: {pos}",
            (margined_x, top + c.MARGIN_Y),
            align="left",
        )

        species_in_ark: dict[int, list[bool]] = {
            sid: [False, False] for sid in self.engine.species_stats.keys()
        }

        for animal in animals:
            sid = animal.species_id
            if animal.gender == Gender.Male:
                species_in_ark[sid][0] = True
            elif animal.gender == Gender.Female:
                species_in_ark[sid][1] = True

        y = top + c.MARGIN_Y * 2
        for sid, (has_male, has_female) in species_in_ark.items():
            self.write_at(self.small_font, f"{sid}: ", (margined_x, y), align="left")

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

    def draw_helpers(self):
        for helper in self.engine.helpers:
            helper_x, helper_y = helper.position
            helper_center = coords_to_px(helper_x, helper_y)

            pygame.draw.circle(
                self.screen, c.HELPER_COLOR, helper_center, c.HELPER_RADIUS
            )
            self.drawn_objects[(helper_center, c.HELPER_RADIUS)] = helper

    def draw_animals(self):
        for animal, cell in self.engine.free_animals.items():
            animal_center = coords_to_px(cell.x, cell.y)

            color = (
                c.MALE_ANIMAL_COLOR
                if animal.gender == Gender.Male
                else c.FEMALE_ANIMAL_COLOR
            )

            animal_rect = pygame.Rect(
                animal_center[0] - c.ANIMAL_RADIUS / 2,
                animal_center[1] - c.ANIMAL_RADIUS / 2,
                c.ANIMAL_RADIUS,
                c.ANIMAL_RADIUS,
            )
            pygame.draw.rect(self.screen, color, animal_rect, c.ANIMAL_RADIUS)

            self.drawn_objects[(animal_center, c.ANIMAL_RADIUS)] = animal

    def draw_if_hovered(self):
        pos = pygame.mouse.get_pos()

        for (center, radius), object in self.drawn_objects.items():
            if is_hovered_circle(pos, center, radius):

                match object:
                    case Ark(position=p, animals=a):
                        self.draw_hovered_ark(p, a)
                    case Player(id=id, position=p, flock=f):
                        print(f"hovering PLAYER, id={id}, pos={p}, flock={f}")
                    case Animal(species_id=s, gender=g):
                        print(f"hovering ANIMAL, species_id={s}, gender={g}")
                break

    def draw_objects(self):
        self.drawn_objects.clear()
        self.draw_ark()
        self.draw_helpers()
        self.draw_animals()

        self.draw_if_hovered()

    def draw_info_panel(self):
        info_pane_x = c.LANDSCAPE_EAST_PX + c.MARGIN_X
        info_pane_y = c.MARGIN_Y

        info_lines = [
            f"{self.engine.helpers[0]}",
            "",
            f"Turn: {self.engine.time_elapsed}/{self.engine.time}",
            # f"Total Growth: {self.garden.total_growth():.2f}",
            f"Helpers: {len(self.engine.helpers)}",
            f"is_raining: {self.engine.is_raining()}",
            # "",
            # f"{'PAUSED' if self.paused else 'RUNNING'}",
            f"{'DEBUG ON' if self.debug_mode else 'DEBUG OFF'}",  # NEW: Show debug status
        ]

        last = 0
        for i, line in enumerate(info_lines):
            y = info_pane_y + i * 30
            if line:  # Skip empty debug line when not in debug mode
                text = self.big_font.render(line, True, (0, 0, 0))
                self.screen.blit(text, (info_pane_x, y))
            last = y

        # species = {sid: }

    def draw_debug_helper_screens(self):
        grid = pygame.Rect(
            c.MARGIN_X, c.MARGIN_Y, c.LANDSCAPE_WIDTH, c.LANDSCAPE_HEIGHT
        )

        mask = pygame.Surface((grid.w, grid.h), pygame.SRCALPHA)
        mask.fill((0, 0, 0, 50))

        for helper in self.engine.helpers:
            grid_center = coords_to_px(*helper.position)
            center = grid_center[0] - grid.x, grid_center[1] - grid.y
            radius = km_to_px(c.MAX_SIGHT_KM)

            pygame.draw.circle(mask, (0, 0, 0, 0), center, radius)

        for helper in self.engine.helpers:
            grid_center = coords_to_px(*helper.position)
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

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_SPACE:
                    self.paused = not self.paused
                elif event.key == pygame.K_RIGHT and self.paused:
                    self.step_simulation()
                elif event.key == pygame.K_d:  # NEW: Toggle debug mode
                    self.debug_mode = not self.debug_mode

    def run(self) -> dict:
        while self.running:
            self.screen.fill(self.bg_color)
            self.draw_grid()
            self.draw_objects()
            self.draw_info_panel()
            self.draw_debug_info()

            self.handle_events()

            if not self.paused:
                self.step_simulation()

            pygame.display.flip()
            self.clock.tick(60)

        pygame.quit()

        return {}
