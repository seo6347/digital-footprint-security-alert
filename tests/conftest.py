from pathlib import Path
from runpy import run_path

import pytest


@pytest.fixture(scope="session")
def v02_fixtures():
    return run_path(str(Path(__file__).parent / "fixtures" / "v02" / "stages.py"))
