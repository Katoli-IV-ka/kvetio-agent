"""pytest conftest — добавляет scripts/ в sys.path.

Позволяет тестам делать:
    from normalize import normalize_domain
    from models import Company
    from greenhouse import GreenhouseAdapter
    from supabase_store import SupabaseStore
    from score import score

без установки пакета через pip.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
