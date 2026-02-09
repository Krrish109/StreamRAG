"""Language extractor registry and factory."""

from typing import Dict, List, Optional

from streamrag.languages.base import LanguageExtractor


class ExtractorRegistry:
    """Registry for language extractors.

    Usage:
        registry = ExtractorRegistry()
        registry.register(PythonExtractor())
        extractor = registry.get_extractor("main.py")
    """

    def __init__(self) -> None:
        self._extractors: List[LanguageExtractor] = []
        self._extension_cache: Dict[str, LanguageExtractor] = {}

    def register(self, extractor: LanguageExtractor) -> None:
        """Register a language extractor."""
        self._extractors.append(extractor)
        for ext in extractor.supported_extensions:
            self._extension_cache[ext] = extractor

    def get_extractor(self, file_path: str) -> Optional[LanguageExtractor]:
        """Find the appropriate extractor for a file.

        Strategy:
        1. Fast path: check extension cache
        2. Slow path: call can_handle on each registered extractor
        """
        for ext, extractor in self._extension_cache.items():
            if file_path.endswith(ext):
                return extractor

        for extractor in self._extractors:
            if extractor.can_handle(file_path):
                return extractor

        return None

    @property
    def supported_languages(self) -> List[str]:
        return [e.language_id for e in self._extractors]

    def can_handle(self, file_path: str) -> bool:
        return self.get_extractor(file_path) is not None


def create_default_registry() -> ExtractorRegistry:
    """Create a registry with all built-in extractors."""
    from streamrag.languages.python import PythonExtractor
    from streamrag.languages.typescript import TypeScriptExtractor
    from streamrag.languages.javascript import JavaScriptExtractor
    from streamrag.languages.rust import RustExtractor
    from streamrag.languages.cpp import CppExtractor
    from streamrag.languages.c import CExtractor
    from streamrag.languages.java import JavaExtractor

    registry = ExtractorRegistry()
    registry.register(PythonExtractor())
    registry.register(TypeScriptExtractor())
    registry.register(JavaScriptExtractor())
    registry.register(RustExtractor())
    registry.register(CppExtractor())
    registry.register(CExtractor())
    registry.register(JavaExtractor())
    return registry
