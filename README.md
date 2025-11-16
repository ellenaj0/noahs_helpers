# Noah's helpers

This is the simulator for [COMS 4444, F25 project 4](https://www.cs.columbia.edu/~kar/4444f25/node21.html)

### CLI Arguments

The simulation can be configured using a variety of command-line arguments.

#### General Options

| Argument     | Default      | Description                                                                                                                                     |
| :----------- | :----------- | :---------------------------------------------------------------------------------------------------------------------------------------------- |
| `--gui`      | `False`      | Launches the graphical user interface to visualize the simulation. If omitted, the simulation runs in the command line and outputs a JSON blob. |
| `-T`         | `No default` | Sets the total number of turns to run the simulation for.                                                                                       |
| `--map_path` | `No default` | Specify num_helpers, animal populations and Ark position in a json file. Must be under `maps/`.                                                 |
| `--player`   | `r`          | Specify the player to run, either `r` for random or `1-10` for a group.                                                                         |
| `--ark`      | `No default` | Specify the ark position as two numbers in the form of `X Y`.                                                                                   |
| `--seed`     | `No default` | Provides a seed for the random number generator to ensure reproducible simulations.                                                             |

### Code Quality and Formatting

The repository uses Ruff for both formatting and linting, if your PR does not pass the CI checks it won't be merged.

VSCode has a Ruff extension that can run on save. [Editor Setup](https://docs.astral.sh/ruff/editors/setup/).

To run formatting check:

```bash
uv run ruff format --check
```

To run formatting:

```bash
uv run ruff format
```

To run linting:

```bash
uv run ruff check
```

To run linting with auto-fix:

```bash
uv run ruff check --fix
```

---

### Usage Examples

To run the simulator, values for these three flags **must** be set:

- `--num_helpers`: integer >= 2
- `--animals`: space-separated sequence of integers >= 2
- `--ark`: two space-separated integers X and Y, 0 <= X, Y < 1000

Here are some common examples of how to run the simulator with different configurations.

##### Example 0: Get help

The simulator provides a usage/help menu given the `-h` / `--help` flag.
This will output all relevant flags and options.

```bash
uv run main.py -h
```

##### Example 1: Minimal config

The minimal required flags (listed above) are shown below.
This will run the random player, generate a random `T` and a random `--seed`.

```bash
uv run main.py --num_helpers 4 --animals 200 40 5 --ark 20 80 # add `--gui` for visualization
```

##### Example 1: Run a specific player

To run a specific player, supply the same arguments as above, but include the `--player` flag.
The `--player` flag accepts either an `r` or a number `1-10`.
This will run the random player, generate a random `T` and a random `--seed`.

```bash
uv run main.py --player r --num_helpers 4 --animals 200 40 5 --ark 20 80 # add `--gui` for visualization
```

##### Example 2: Run a Simulator with existing map configs.

Map configurations can be stored as json files under the `maps/` directory.
If a path is supplied, it must contain exactly the required options specified above and they cannot then be specified as program arguments.
This will run the random player, generate a random `T` and a random `--seed`.

```bash
uv run main.py --map_path maps/template/t1.json # add `--gui` for visualization
```

##### Example 3: Specify everything

For maximum control, specify all arguments like so:

```bash
uv run main.py --num_helpers 8 --animals 10 20 30 40 --ark 150 850 -T 3000 --seed 4444 # add `--gui` for visualization
```
