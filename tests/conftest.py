import asyncio
from pathlib import Path
from runpy import run_path

import pytest


@pytest.fixture(scope="module")
def offline_async_runner():
    # Windows creates a loopback wakeup socket while initializing the loop.
    # Open it before the function-scoped network guards, which stay active
    # throughout the coroutine and its mocked transport.
    with asyncio.Runner() as runner:
        yield runner


@pytest.fixture(scope="session")
def v02_fixtures():
    return run_path(str(Path(__file__).parent / "fixtures" / "v02" / "stages.py"))
