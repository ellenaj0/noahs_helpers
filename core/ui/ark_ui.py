import pygame

from core.animal import Gender
from core.engine import Engine
import core.constants as c


def coords_to_px(x: float, y: float) -> tuple[float, float]:
    x_px = c.LANDSCAPE_WEST_PX + (c.LANDSCAPE_EAST_PX - c.LANDSCAPE_WEST_PX) * x / c.X
    y_px = (
        c.LANDSCAPE_NORTH_PX + (c.LANDSCAPE_SOUTH_PX - c.LANDSCAPE_NORTH_PX) * y / c.Y
    )
    return x_px, y_px


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
        self.big_font = pygame.font.Font(None, 32)
        self.small_font = pygame.font.Font(None, 20)

    def write_at(self, line: str, coord: tuple[float, float]):
        text = self.small_font.render(line, True, (0, 0, 0))
        self.screen.blit(text, coord)

    def draw_grid(self):
        """Draw garden boundaries and grid."""
        border_rect = pygame.Rect(
            c.MARGIN_X, c.MARGIN_Y, c.LANDSCAPE_WIDTH, c.LANDSCAPE_HEIGHT
        )
        pygame.draw.rect(self.screen, c.GRID_COLOR, border_rect)  # fill
        pygame.draw.rect(self.screen, (0, 0, 0), border_rect, 2)  # border

        for i in range(c.NUM_GRID_LINES + 1):
            x = c.MARGIN_X + c.LANDSCAPE_WIDTH * i / c.NUM_GRID_LINES

            if i not in [0, c.NUM_GRID_LINES]:
                # only draw lines inside the grid
                pygame.draw.line(
                    self.screen,
                    c.GRIDLINE_COLOR,
                    (x, c.MARGIN_Y),
                    (x, c.MARGIN_Y + c.LANDSCAPE_HEIGHT),
                )

            line = "  X"
            if i:
                val = c.X * i / c.NUM_GRID_LINES
                line = f"{int(val)}" if val.is_integer() else f"{val:.1f}"
            self.write_at(line, (x - 5, c.MARGIN_Y - 20))

        for i in range(c.NUM_GRID_LINES + 1):
            y = c.MARGIN_Y + c.LANDSCAPE_HEIGHT * i / c.NUM_GRID_LINES

            if i not in [0, c.NUM_GRID_LINES]:
                pygame.draw.line(
                    self.screen,
                    c.GRIDLINE_COLOR,
                    (c.MARGIN_X, y),
                    (c.MARGIN_X + c.LANDSCAPE_WIDTH, y),
                )

            line = "  Y"
            if i:
                val = c.Y * i / c.NUM_GRID_LINES
                line = f"{int(val)}" if val.is_integer() else f"{val:.1f}"
            self.write_at(line, (c.MARGIN_X - 30, y - 5))

    def draw_ark(self):
        ark_x, ark_y = self.engine.ark.position
        ark_x_px, ark_y_px = coords_to_px(ark_x, ark_y)

        pygame.draw.circle(self.screen, c.ARK_COLOR, (ark_x_px, ark_y_px), c.ARK_RADIUS)

    def draw_helpers(self):
        for helper in self.engine.helpers:
            helper_x, helper_y = helper.position
            helper_x_px, helper_y_px = coords_to_px(helper_x, helper_y)

            pygame.draw.circle(
                self.screen, c.HELPER_COLOR, (helper_x_px, helper_y_px), c.HELPER_RADIUS
            )

    def draw_animals(self):
        for animal, cell in self.engine.free_animals.items():
            a_x_px, a_y_px = coords_to_px(cell.x, cell.y)

            color = (
                c.MALE_ANIMAL_COLOR
                if animal.gender == Gender.Female
                else c.FEMALE_ANIMAL_COLOR
            )

            animal_rect = pygame.Rect(a_x_px, a_y_px, c.ANIMAL_RADIUS, c.ANIMAL_RADIUS)
            pygame.draw.rect(self.screen, color, animal_rect, c.ANIMAL_RADIUS)

    def draw_objects(self):
        self.draw_ark()
        self.draw_helpers()
        self.draw_animals()

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
            # f"{'DEBUG ON' if self.debug_mode else 'DEBUG OFF'}",  # NEW: Show debug status
        ]

        for i, line in enumerate(info_lines):
            y = info_pane_y + i * 30
            if line:  # Skip empty debug line when not in debug mode
                text = self.big_font.render(line, True, (0, 0, 0))
                self.screen.blit(text, (info_pane_x, y))

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
                # print(f"event {event.key}")
                if event.key == pygame.K_SPACE:
                    print("pressed space")
                    self.paused = not self.paused
                elif event.key == pygame.K_RIGHT and self.paused:
                    print("pressed right")
                    self.step_simulation()
                elif event.key == pygame.K_d:  # NEW: Toggle debug mode
                    print("toggle debug mode")
                #     self.debug_mode = not self.debug_mode

    def run(self) -> dict:
        while self.running:
            self.handle_events()

            if not self.paused:
                self.step_simulation()
                # self.clock.tick(40)

            self.screen.fill(self.bg_color)
            self.draw_grid()
            self.draw_objects()
            self.draw_info_panel()
            # self.draw_debug_info()

            pygame.display.flip()
            self.clock.tick(100)

        pygame.quit()

        return {}
