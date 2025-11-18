"""Constants used by Player5 strategy."""
import math
from typing import Tuple
from core.animal import Gender

# Map boundaries
MAX_MAP_COORD = 999
MIN_MAP_COORD = 0

# Movement constants
TARGET_POINT_DISTANCE = 150.0
BACKTRACK_MIN_ANGLE = math.radians(160)
BACKTRACK_MAX_ANGLE = math.radians(200)
NEAR_ARK_DISTANCE = 150.0
SAFE_RADIUS_FROM_ARK = 1000.0

# Type alias
SpeciesGender = Tuple[int, Gender]
