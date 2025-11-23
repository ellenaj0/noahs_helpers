# Independent Player - Radial Exploration Strategy

An intelligent helper agent for Noah's Ark simulation that uses radial sector-based exploration with dynamic animal tracking to efficiently collect animals before the flood.

## Table of Contents
- [Overview](#overview)
- [Features](#features)
- [Installation](#installation)
- [Usage](#usage)
- [Algorithm](#algorithm)
- [Performance](#performance)
- [Configuration](#configuration)
- [File Structure](#file-structure)

## Overview

This implementation solves the Noah's Ark helper problem where multiple agents must explore a 1000×1000 km landscape, locate animals, and shepherd them back to the ark before a deadline. The solution uses an intelligent sector-based radial exploration strategy with dynamic animal tracking, optimized return paths, and adaptive sector allocation.

**Key Innovations**: 
1. Dynamic species tracking (catch rate 0% → 25%)
2. Two-phase return path with clockwise offset (18° coverage increase)
3. Inverse sector weighting based on ark position (balanced exploration)

## Features

### 1. Intelligent Sector-Based Exploration
- **Inverse Area Weighting**: Larger explorable areas get smaller sector angles (more efficient coverage)
  - North direction (large area): smaller angle (~40°)
  - South direction (small area): larger angle (~70°)
  - Formula: `weight = 1 / distance^0.8` for soft inverse weighting
- **Helper Assignment**: Excludes Noah (id=0), assigns sectors to actual helpers (id=1..n-1)
- **Smart Direction Selection**: Next angle maximizes distance from:
  - Previously explored outbound angles
  - Previously explored return angles
  - Sector boundaries
  - Example: Sector 0-90°, explored outbound [0°], return [10°] → next: ~50°

### 2. Dynamic Animal Tracking
- **Species Tracking**: Records target species ID when hunting starts
- **Position Updates**: Re-locates target species each turn (animals move with 50% probability)
- **Adaptive Pursuit**: Follows moving animals instead of going to fixed locations
- **Smart Filtering**: 
  - Skips animals already in own flock
  - Skips Unknown gender animals when other helpers are in same cell (likely shepherded)
  - Prevents hunting other helpers' animals

### 3. Optimized Return Strategy
- **Return Triggers**: 
  - Captured any animals (1+)
  - Time constraint requires immediate return
- **Two-Phase Return Path**:
  - **Phase 1 (>100km)**: Clockwise offset to explore new areas
    - Offset formula: `min(30°, distance/15)` - larger offset when farther
    - Explores different regions than outbound path
  - **Phase 2 (≤100km)**: Direct path to ark for efficient return
- **Opportunistic Hunting**: Continues catching needed animals during return journey
- **Capacity Maximization**: Fills flock to 4 animals when possible

### 4. Anti-Loop Protection
- **Hunt Cooldown**: Won't re-hunt within 10 cells of last hunt position for 20 turns
- **Discovery Position**: Returns to position where hunt started before resuming journey
- **State Management**: Properly transitions between exploring, hunting, and returning states

### 5. Intelligent Time Management
- **Before Rain**: Assumes infinite time (10000 turns) to maximize exploration
- **After Rain**: Precise countdown with 100-turn safety margin
- **Rain Detection**: Tracks rain start time (T - 1008) for exact calculations
- **Dynamic Constraints**: Never ventures beyond safe return distance
- **Completion Detection**: Stops exploring when all species have both genders

## Installation

### Prerequisites
- Python 3.13+
- pygame 2.6.1+
- UV package manager (recommended) or pip

### Setup
```bash
# Clone the repository
cd noahs_helpers/players/group10

# The player is automatically loaded via the wrapper
# No additional installation needed
```

## Usage

### Running Tests
```bash
# Run with default parameters
bash test.sh

# Run with custom parameters
uv run main.py --player 10 --num_helpers 8 \
  --animals 20 40 60 80 100 120 \
  --ark 500 500 -T 2500 --seed 12345
```

### Running with GUI
```bash
# Enable GUI in test.sh
GUI="true"
bash test.sh

# Or directly
uv run main.py --player 10 --num_helpers 4 \
  --animals 30 40 --ark 500 500 -T 2200 --seed 42 --gui
```

### Integration
The player is integrated via the wrapper in `players/group10/player.py`:
```python
from player import IndependentPlayer
Player10 = IndependentPlayer
```

## Algorithm

### State Machine
```
at_ark → exploring → hunting → returning_to_discovery → returning → at_ark
                         ↓                                    ↓
                    (catch animal)                    (deliver to ark)
```

**States:**
- `exploring` - Moving outward along assigned heading
- `hunting` - Actively pursuing target species
- `returning_to_discovery` - Returning to where hunt started
- `returning` - Moving back to ark with animals
- `at_ark` - Delivering animals and choosing next direction

### High-Level Flow

#### Initialization
1. Assign sector to helper based on ID
2. Set initial heading angle
3. Start at ark position (500, 500)

#### Main Loop (Priority System)
Each turn processes actions in priority order:

1. **Priority 1** - Release duplicate animals (ark already has)
2. **Priority 2** - Obtain animals in current cell (known gender only)
3. **Priority 3** - Return to discovery position after catching animal
4. **Priority 4** - Track and move towards target animal (dynamic position update)
5. **Priority 5** - Search for needed animals in sight, start hunting
6. **Priority 6** - Continue exploring or returning

#### Animal Selection Criteria
**Always Hunt:**
- Known gender animals that ark needs

**Skip:**
- Animals already in own flock
- Unknown gender animals when other helpers in same cell (likely shepherded)
- Species where ark has both genders
- Unknown gender animals when time < 200 turns (focus on returning)

**Consider (Unknown gender):**
- No other helpers in cell AND species incomplete
- Time remaining > 200 turns

#### Return Path Strategy

**Phase 1 - Far from Ark (>100km):**
1. Calculate angle to ark
2. Add clockwise offset: `min(30°, distance/15)`
3. Move in offset direction (explores new areas)
4. Record return angle as explored

**Phase 2 - Close to Ark (≤100km):**
1. Move directly toward ark
2. No offset (efficient return)

**Example**: Starting 300km away at 240° → returns at ~260° (+20° offset) → direct path at 100km

#### Next Exploration Direction Selection

After delivering animals to ark:

1. Generate 72 candidate angles within assigned sector
2. For each candidate, calculate minimum distance to ALL obstacles:
   - All explored outbound angles
   - All explored return angles
   - Sector start boundary
   - Sector end boundary
3. Select candidate with maximum minimum distance

**Result**: Maximizes coverage by avoiding all previously explored directions.

For detailed algorithm description, see [`1st_trivial_algorithm.txt`](./1st_trivial_algorithm.txt).

## Performance

### Benchmark Results

**Test Configuration**: 8 helpers, 10 species (10, 20, 40, 60, 80, 100, 120, 140, 160, 180 animals), Ark at (550, 350), Seed 12345

| Metric | Value |
|--------|-------|
| **Final Score** | 802/1000 |
| **Success Rate** | 100% (all helpers returned) |
| **Execution Time** | ~1.5 seconds (2500 turns) |
| **Performance** | ~527 turns/second |

### Key Improvements

| Feature | Description | Impact |
|---------|-------------|--------|
| **Dynamic Tracking** | Follow moving animals vs fixed locations | Catch rate 0% → 25% |
| **Return Path Offset** | Two-phase return with clockwise offset | +18° coverage difference |
| **Inverse Weighting** | Larger areas get smaller angles | Balanced exploration |
| **Smart Filtering** | Skip other helpers' animals | Prevents hunting loops |
| **Completion Detection** | Stop when all species collected | Saves time & energy |
| **Anti-Stuck** | Multiple protections | 100% reliability |

**Key Innovations**: 
1. Dynamic species tracking for moving animals
2. Two-phase return path optimization
3. Inverse sector weighting based on ark position

## Configuration

### Test Parameters

Modify `test.sh` to customize simulation:

```bash
PLAYER="10"                                      # Player ID
NUM_HELPERS=8                                    # Number of helpers (1 Noah + 7 helpers)
ANIMALS="10 20 40 60 80 100 120 140 160 180"    # Animal populations (10 species)
ARK_X=550                                        # Ark X coordinate
ARK_Y=350                                        # Ark Y coordinate
TIME=2500                                        # Simulation duration (turns)
SEED=12345                                       # Random seed
GUI="true"                                       # Enable/disable visualization
```

### Command Line Options

```bash
--player 10           # Use Independent Player
--num_helpers N       # Number of helpers
--animals N1 N2 ...   # Animal populations
--ark X Y             # Ark position
-T N                  # Time limit
--seed N              # Random seed
--gui                 # Enable visualization
```

## File Structure

```
1st-Independent Player 1114/
├── player.py                      # Main implementation (~860 lines)
├── 1st_trivial_algorithm.txt      # Detailed algorithm description
└── README.md                      # This file
```

### Key Components in player.py

- **IndependentPlayer class**: Main player implementation
- **State machine**: exploring → hunting → returning_to_discovery → returning → at_ark
- **Helper methods**:
  - `_explore()` - Radial outbound exploration
  - `_return_to_ark()` - Two-phase return with offset
  - `_find_nearest_needed_animal()` - Smart animal filtering
  - `_choose_next_exploration_angle()` - Direction optimization
  - `_move_towards_cell()` / `_move_towards_position()` - Movement utilities
  - `_get_available_turns()` - Time management
  - `_sync_ark_information()` - Shared state synchronization

## See Also

- [Project Specification](../../../README.md) - Full problem description
- [Algorithm Details](./1st_trivial_algorithm.txt) - Complete algorithm specification
- [Test Script](../test.sh) - Default test configuration

