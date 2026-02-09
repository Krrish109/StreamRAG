"""StreamRAG language support."""

from streamrag.languages.base import LanguageExtractor
from streamrag.languages.registry import ExtractorRegistry, create_default_registry

__all__ = ["LanguageExtractor", "ExtractorRegistry", "create_default_registry"]
