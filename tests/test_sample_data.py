"""Run with: python3 tests/test_sample_data.py"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schema import Scheme  # noqa: E402

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "sample_schemes.json")


def test_sample_schemes_validate():
    with open(DATA_PATH) as f:
        raw = json.load(f)

    schemes = [Scheme(**item) for item in raw]
    assert len(schemes) == 3
    for s in schemes:
        print(f"OK  {s.scheme_id:35s} | {s.category:12s} | age_min={s.eligibility.age_min} income_max={s.eligibility.income_max}")


if __name__ == "__main__":
    test_sample_schemes_validate()
