"""Tests for language abstraction layer."""

import pytest

from streamrag.extractor import ASTExtractor, extract
from streamrag.languages.base import LanguageExtractor
from streamrag.languages.python import PythonExtractor
from streamrag.languages.registry import ExtractorRegistry, create_default_registry


def test_python_extractor_can_handle():
    ext = PythonExtractor()
    assert ext.can_handle("main.py") is True
    assert ext.can_handle("types.pyi") is True
    assert ext.can_handle("app.js") is False
    assert ext.can_handle("lib.rs") is False
    assert ext.can_handle("main.go") is False


def test_python_extractor_language_id():
    ext = PythonExtractor()
    assert ext.language_id == "python"


def test_python_extractor_extract_matches_original():
    """PythonExtractor produces same output as ASTExtractor."""
    code = "def foo(x):\n    return x + 1\n"
    original = extract(code)
    wrapped = PythonExtractor().extract(code, "test.py")
    assert len(original) == len(wrapped)
    assert original[0].name == wrapped[0].name
    assert original[0].signature_hash == wrapped[0].signature_hash


def test_registry_register_and_lookup():
    registry = ExtractorRegistry()
    registry.register(PythonExtractor())
    ext = registry.get_extractor("main.py")
    assert ext is not None
    assert ext.language_id == "python"


def test_registry_unknown_extension():
    registry = ExtractorRegistry()
    registry.register(PythonExtractor())
    assert registry.get_extractor("main.rs") is None
    assert registry.can_handle("main.rs") is False


def test_create_default_registry():
    registry = create_default_registry()
    assert registry.can_handle("main.py") is True
    assert "python" in registry.supported_languages
    # New languages are registered
    assert registry.can_handle("app.ts") is True
    assert registry.can_handle("app.js") is True
    assert registry.can_handle("lib.rs") is True
    assert registry.can_handle("main.cpp") is True
    assert registry.can_handle("main.c") is True
    assert registry.can_handle("App.java") is True
    assert "typescript" in registry.supported_languages
    assert "javascript" in registry.supported_languages
    assert "rust" in registry.supported_languages
    assert "cpp" in registry.supported_languages
    assert "c" in registry.supported_languages
    assert "java" in registry.supported_languages
    # Unsupported should still return False
    assert registry.can_handle("main.go") is False
    assert registry.can_handle("main.rb") is False


def test_language_extractor_abc():
    """Cannot instantiate LanguageExtractor directly."""
    with pytest.raises(TypeError):
        LanguageExtractor()
