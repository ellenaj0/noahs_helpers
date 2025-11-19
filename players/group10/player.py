import sys
from pathlib import Path

# Add subdirectory to path and import IndependentPlayer
sys.path.insert(0, str(Path(__file__).parent / "1st-Independent Player 1114"))
from player import IndependentPlayer

# Player10 references the IndependentPlayer implementation
Player10 = IndependentPlayer
