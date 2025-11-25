import sys
from pathlib import Path

# Ensure project root (parent of tests/) is on sys.path so tests can import main
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
