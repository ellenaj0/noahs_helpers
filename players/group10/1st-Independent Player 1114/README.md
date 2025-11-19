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

This implementation solves the Noah's Ark helper problem where multiple agents must explore a 1000×1000 km landscape, locate animals, and shepherd them back to the ark before a deadline. The solution uses a sector-based radial exploration strategy with dynamic animal tracking to maximize efficiency.

**Key Innovation**: Dynamic species tracking that follows moving animals instead of going to fixed locations, improving catch rate from 0% to 25%.

## Features

### 1. Sector-Based Exploration
- **Area Division**: 360° space divided evenly among helpers (e.g., 4 helpers → 90° sectors each)
- **Initial Direction**: Helper i starts at angle i × (360/n)
- **Smart Direction Selection**: Next angle maximizes distance from both:
  - Previously explored directions
  - Sector boundaries
  - Example: Sector 0-90°, explored [0°] → next: 45°

### 2. Dynamic Animal Tracking
- **Species Tracking**: Records target species ID when hunting starts
- **Position Updates**: Re-locates target species each turn (animals move with 50% probability)
- **Adaptive Pursuit**: Follows moving animals instead of going to fixed locations
- **Smart Filtering**: Skips animals already shepherded by other helpers

### 3. Flexible Return Strategy
- **Return Triggers**: 
  - Captured 2+ animals
  - Flock full (4 animals)
  - Time constraint requires immediate return
- **Opportunistic Hunting**: Continues catching needed animals during return journey
- **Capacity Maximization**: Fills flock to 4 animals when possible

### 4. Anti-Loop Protection
- **Hunt Cooldown**: Won't re-hunt within 10 cells of last hunt position for 20 turns
- **Discovery Position**: Returns to position where hunt started before resuming journey
- **State Management**: Properly transitions between exploring, hunting, and returning states

### 5. Time Management
- **Safety Margin**: Returns 100 turns before deadline
- **Rain Awareness**: Tracks rain start time (T - 1008) for precise calculations
- **Dynamic Constraints**: Never ventures beyond safe return distance

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
- Ark doesn't have both genders of this species
- Animal not already in helper's flock
- For unknown gender animals:
  - In same cell but gender unknown → skip (likely shepherded)
  - Outside cell and species incomplete → consider hunting
  - Time remaining > 200 turns for unknown gender hunts

#### Direction Selection (After Delivery)
When returning to ark with animals:

1. Generate 72 candidate angles within sector
2. For each candidate, calculate minimum distance to:
   - All explored angles
   - Sector start boundary  
   - Sector end boundary
3. Select candidate with maximum minimum distance (furthest from all obstacles)

**Example**: Sector 0-90°, explored [0°] → choose 45° (equidistant from 0° and 90°)

For detailed algorithm description, see [`1st_trivial_algorithm.txt`](./1st_trivial_algorithm.txt).

## Performance

### Benchmark Results

**Test Configuration**: 8 helpers, 6 species (20, 40, 60, 80, 100, 120 animals), Seed 12345

| Metric | Value |
|--------|-------|
| **Final Score** | 501 |
| **Success Rate** | 100% (all helpers returned) |
| **Execution Time** | 1.0 second (2500 turns) |
| **Performance** | 2,460 turns/second |

### Improvements Over Baseline

| Feature | Before | After | Improvement |
|---------|--------|-------|-------------|
| **Catch Rate** | 0% | 25% | ✅ +25% |
| **Score** | 204 | 501 | ✅ +145% |
| **Stuck Helpers** | Yes | No | ✅ 100% reliable |

**Key Innovation**: Dynamic species tracking (following moving animals) instead of going to fixed locations.

## Configuration

### Test Parameters

Modify `test.sh` to customize simulation:

```bash
PLAYER="10"                    # Player ID
NUM_HELPERS=8                  # Number of helpers
ANIMALS="20 40 60 80 100 120"  # Animal populations per species
ARK_X=500                      # Ark X coordinate
ARK_Y=500                      # Ark Y coordinate
TIME=2500                      # Simulation duration (turns)
SEED=12345                     # Random seed
GUI="false"                    # Enable/disable visualization
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
├── player.py                      # Main implementation (681 lines)
├── 1st_trivial_algorithm.txt      # Detailed algorithm description
└── README.md                      # This file
```

## See Also

- [Project Specification](../../../README.md) - Full problem description
- [Algorithm Details](./1st_trivial_algorithm.txt) - Complete algorithm specification
- [Test Script](../test.sh) - Default test configuration

