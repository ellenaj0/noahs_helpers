from random import choice, uniform
from math import cos, sin, pi, atan2

import core.constants as c
from core.views.player_view import Kind


# Sector constants
MAX_SEARCH_RADIUS = 1000.0
SECTOR_INTEGRATION_STEPS = 200
SECTOR_BINARY_SEARCH_ITERATIONS = 50
SECTOR_OVERLAP_PERCENT = 0
POSITION_GENERATION_ATTEMPTS = 100


class SectorManager:
    """Manages sector calculation and position generation for helpers."""

    def __init__(
        self,
        ark_position: tuple[int, int],
        kind: "Kind",
        num_helpers: int,
        helper_id: int,
    ):
        self.ark_position = ark_position
        self.kind = kind
        self.num_helpers = num_helpers
        self.helper_id = helper_id

        self.sector_start_angle: float = 0.0
        self.sector_end_angle: float = 2 * pi

        self._initialize_sector()

    def _max_radius_at_angle(
        self, angle: float, radius: float = MAX_SEARCH_RADIUS
    ) -> float:
        """Calculate the maximum radius at a given angle such that the point stays within grid bounds."""
        ark_x, ark_y = self.ark_position
        cos_a = cos(angle)
        sin_a = sin(angle)

        max_r = radius
        epsilon = 1e-10

        # X boundaries
        if abs(cos_a) > epsilon:
            if cos_a < 0:
                r_to_x0 = -ark_x / cos_a
                if r_to_x0 > 0:
                    max_r = min(max_r, r_to_x0)
            if cos_a > 0:
                r_to_xmax = (c.X - ark_x) / cos_a
                if r_to_xmax > 0:
                    max_r = min(max_r, r_to_xmax)

        # Y boundaries
        if abs(sin_a) > epsilon:
            if sin_a < 0:
                r_to_y0 = -ark_y / sin_a
                if r_to_y0 > 0:
                    max_r = min(max_r, r_to_y0)
            if sin_a > 0:
                r_to_ymax = (c.Y - ark_y) / sin_a
                if r_to_ymax > 0:
                    max_r = min(max_r, r_to_ymax)

        return max(0, max_r)

    def _calculate_sector_area(
        self, start_angle: float, end_angle: float, radius: float = MAX_SEARCH_RADIUS
    ) -> float:
        """Calculate the area of a sector clipped by grid boundaries using numerical integration."""
        if start_angle > end_angle:
            # Sector wraps around 0
            area1 = self._calculate_sector_area(start_angle, 2 * pi, radius)
            area2 = self._calculate_sector_area(0, end_angle, radius)
            return area1 + area2

        num_steps = SECTOR_INTEGRATION_STEPS
        dtheta = (end_angle - start_angle) / num_steps

        area = 0.0
        for i in range(num_steps + 1):
            angle = start_angle + i * dtheta
            r_max = self._max_radius_at_angle(angle, radius)

            # Simpson's rule weights: 1, 4, 2, 4, ..., 1
            if i == 0 or i == num_steps:
                weight = 1.0
            elif i % 2 == 1:
                weight = 4.0
            else:
                weight = 2.0

            area += weight * (r_max**2) / 2.0

        return area * dtheta / 3.0

    def _calculate_cumulative_area(
        self, end_angle: float, radius: float = MAX_SEARCH_RADIUS
    ) -> float:
        """Calculate cumulative area from angle 0 to end_angle."""
        if end_angle <= 0:
            return 0.0
        if end_angle >= 2 * pi:
            return self._calculate_sector_area(0, 2 * pi, radius)

        return self._calculate_sector_area(0, end_angle, radius)

    def _find_equal_area_sectors(
        self, num_sectors: int, radius: float = MAX_SEARCH_RADIUS
    ) -> list[float]:
        """Find sector boundaries that divide the searchable area into equal parts."""
        if num_sectors == 0:
            return [0, 2 * pi]

        total_area = self._calculate_sector_area(0, 2 * pi, radius)
        target_area_per_sector = total_area / num_sectors

        boundaries = [0.0]

        for i in range(num_sectors - 1):
            target_cumulative = (i + 1) * target_area_per_sector
            low = boundaries[-1]
            high = boundaries[-1] + 2 * pi

            # Binary search for angle where cumulative area equals target
            for _ in range(SECTOR_BINARY_SEARCH_ITERATIONS):
                mid = (low + high) / 2
                mid_normalized = mid % (2 * pi)
                test_cumulative = self._calculate_cumulative_area(
                    mid_normalized, radius
                )

                if test_cumulative < target_cumulative:
                    low = mid
                else:
                    high = mid

                if abs(high - low) < 0.001:
                    break

            next_boundary = (low + high) / 2 % (2 * pi)
            next_boundary = round(next_boundary, 6)

            # Handle wrap-around case
            if next_boundary < boundaries[-1] and i < num_sectors - 2:
                next_boundary = boundaries[-1] + (2 * pi - boundaries[-1]) / (
                    num_sectors - i
                )
                next_boundary = round(next_boundary, 6)

            boundaries.append(next_boundary)

        # Ensure last boundary is 2*pi
        if abs(boundaries[-1] - 2 * pi) > 0.0001:
            boundaries.append(2 * pi)
        else:
            boundaries[-1] = 2 * pi

        return boundaries

    def _initialize_sector(self):
        """Initialize sector angles for this helper using equal-area sectors."""
        from core.views.player_view import Kind

        if self.kind == Kind.Noah:
            self.sector_start_angle = 0
            self.sector_end_angle = 2 * pi
            return

        num_actual_helpers = max(1, self.num_helpers - 1)
        if num_actual_helpers == 0:
            self.sector_start_angle = 0
            self.sector_end_angle = 2 * pi
            return

        boundaries = self._find_equal_area_sectors(num_actual_helpers)
        sector_index = self.helper_id - 1  # Subtract 1 because id 0 is Noah

        if 0 <= sector_index < len(boundaries) - 1:
            start_angle = boundaries[sector_index]
            end_angle = boundaries[sector_index + 1]
        else:
            # Fallback: last helper gets the last sector
            start_angle = boundaries[-2] if len(boundaries) > 1 else 0
            end_angle = boundaries[-1] if len(boundaries) > 1 else 2 * pi

        # Add overlap on each side
        sector_span = end_angle - start_angle
        if sector_span < 0:
            sector_span += 2 * pi
        overlap = sector_span * SECTOR_OVERLAP_PERCENT

        self.sector_start_angle = (start_angle - overlap) % (2 * pi)
        self.sector_end_angle = (end_angle + overlap) % (2 * pi)

    def is_in_sector(self, x: float, y: float) -> bool:
        """Check if a point is in this helper's sector."""
        dx = x - self.ark_position[0]
        dy = y - self.ark_position[1]
        angle = atan2(dy, dx)
        if angle < 0:
            angle += 2 * pi

        # Handle wrap-around case
        if self.sector_start_angle > self.sector_end_angle:
            return angle >= self.sector_start_angle or angle <= self.sector_end_angle
        else:
            return self.sector_start_angle <= angle <= self.sector_end_angle

    def get_random_position_in_sector(self) -> tuple[float, float]:
        """Generate a random position within sector and within max search radius of ark."""
        for _ in range(POSITION_GENERATION_ATTEMPTS):
            # Generate random angle within sector
            if self.sector_start_angle > self.sector_end_angle:
                # Wraps around
                angle1 = uniform(self.sector_start_angle, 2 * pi)
                angle2 = uniform(0, self.sector_end_angle)
                angle = choice([angle1, angle2])
            else:
                angle = uniform(self.sector_start_angle, self.sector_end_angle)

            dist = uniform(0, MAX_SEARCH_RADIUS)
            ark_x, ark_y = self.ark_position
            x = ark_x + dist * cos(angle)
            y = ark_y + dist * sin(angle)

            # Clamp to grid boundaries
            x = max(0, min(c.X - 1, x))
            y = max(0, min(c.Y - 1, y))

            if self.is_in_sector(x, y):
                return (x, y)

        # Fallback: return a position within max search radius
        angle = uniform(0, 2 * pi)
        dist = uniform(0, MAX_SEARCH_RADIUS)
        ark_x, ark_y = self.ark_position
        x = max(0, min(c.X - 1, ark_x + dist * cos(angle)))
        y = max(0, min(c.Y - 1, ark_y + dist * sin(angle)))
        return (x, y)
