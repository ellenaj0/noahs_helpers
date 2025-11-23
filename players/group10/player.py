import sys
from pathlib import Path

# Add subdirectory to path and import IndependentPlayer
sys.path.insert(0, str(Path(__file__).parent / "2nd-Independent Player 1117"))
from player import IndependentPlayer

# Player10 references the IndependentPlayer implementation
Player10 = IndependentPlayer
