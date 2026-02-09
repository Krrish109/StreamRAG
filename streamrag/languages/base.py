"""Abstract base for language extractors."""

from abc import ABC, abstractmethod
from typing import List

from streamrag.models import ASTEntity


class LanguageExtractor(ABC):
    """Abstract interface for language-specific code extractors.

    Every language extractor must:
    1. Declare which files it can handle (by extension or content inspection)
    2. Extract ASTEntity objects from source code
    """

    @abstractmethod
    def can_handle(self, file_path: str) -> bool:
        """Return True if this extractor can process the given file."""
        ...

    @abstractmethod
    def extract(self, source: str, file_path: str = "") -> List[ASTEntity]:
        """Extract code entities from source code.

        Must return empty list on empty content or parse errors.
        Must not raise exceptions.
        """
        ...

    @property
    @abstractmethod
    def language_id(self) -> str:
        """Return a unique language identifier (e.g., 'python', 'javascript')."""
        ...

    @property
    def supported_extensions(self) -> List[str]:
        """Return list of file extensions this extractor handles."""
        return []
