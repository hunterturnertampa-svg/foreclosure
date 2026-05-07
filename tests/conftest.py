import pytest
from foreclosure_bot.dedupe import Store


@pytest.fixture
def store() -> Store:
    s = Store(":memory:")
    s.init_schema()
    return s
