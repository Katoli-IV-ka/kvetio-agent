"""pytest conftest - adds scripts/ to sys.path.

Allows tests to import script modules without installing the project package.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
