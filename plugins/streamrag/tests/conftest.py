"""Shared pytest fixtures for StreamRAG tests."""

import pytest

from streamrag.graph import LiquidGraph
from streamrag.extractor import ASTExtractor
from streamrag.bridge import DeltaGraphBridge


@pytest.fixture
def empty_graph():
    return LiquidGraph()


@pytest.fixture
def extractor():
    return ASTExtractor()


@pytest.fixture
def bridge():
    return DeltaGraphBridge()


@pytest.fixture
def sample_python_code():
    return '''
def hello(name):
    return f"Hello, {name}"

class UserService:
    def get_user(self, user_id):
        return self.db.query(user_id)

    def delete_user(self, user_id):
        user = self.get_user(user_id)
        self.db.delete(user)
'''


@pytest.fixture
def fifty_functions_code():
    """Generate code with 50 functions."""
    lines = []
    for i in range(50):
        lines.append(f"def func_{i}(x):")
        lines.append(f"    return x + {i}")
        lines.append("")
    return "\n".join(lines)
