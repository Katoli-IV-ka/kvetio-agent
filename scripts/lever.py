"""Lever Postings API — source-адаптер. Stub.

API: GET https://api.lever.co/v0/postings/{company}?mode=json
Auth: не требуется.

CLI:
    python scripts/lever.py --segment medical-imaging

TODO: реализовать по аналогии с greenhouse.py после MVP.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from models import ICPQuery, RawSignal  # noqa: F401


class LeverAdapter:
    name = "lever"
    tier = "A"
    parser_version = "stub"

    def fetch(self, query: ICPQuery):  # noqa: ANN201
        raise NotImplementedError("LeverAdapter — stub. Реализовать после MVP.")
        yield  # pragma: no cover


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lever ATS source adapter (stub)")
    parser.add_argument("--segment", required=True)
    parser.parse_args()
    print(json.dumps([], ensure_ascii=False))
    print("WARNING: LeverAdapter — stub, результатов нет.", file=sys.stderr)
