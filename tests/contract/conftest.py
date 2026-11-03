import json
from pathlib import Path

import pytest


@pytest.fixture
def subject_data():
    return {
        "name": "홍길동",
        "organization": "OO대학교",
        "email": "gildong@univ.ac.kr",
    }


@pytest.fixture
def responses():
    directory = Path(__file__).parents[1] / "fixtures"
    return {
        name: json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))
        for name in (
            "search_response", "profiling_response", "risk_response", "dfsa_result"
        )
    }
