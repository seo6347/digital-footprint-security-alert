import pytest

from dfsa._v01.contracts.search import SearchResult


@pytest.fixture(autouse=True)
def no_real_network(deny_unit_network):
    """Apply the shared network guard to this test package."""


@pytest.fixture
def source():
    return SearchResult(
        source_id="src_001", url="https://example.com/profile",
        normalized_url="https://example.com/untrusted-normalized", rank=1,
        relevance={"status": "candidate", "reasons": ["name_match"]},
        discovered_by=[{"query_id": "q_001"}],
    )
