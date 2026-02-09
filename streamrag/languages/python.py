"""Python language extractor -- wraps the existing ASTExtractor."""

from typing import List

from streamrag.extractor import ASTExtractor
from streamrag.languages.base import LanguageExtractor
from streamrag.models import ASTEntity


class PythonExtractor(LanguageExtractor):
    """Python code extractor using the stdlib ast module."""

    def __init__(self) -> None:
        self._extractor = ASTExtractor()

    @property
    def language_id(self) -> str:
        return "python"

    @property
    def supported_extensions(self) -> List[str]:
        return [".py", ".pyi"]

    def can_handle(self, file_path: str) -> bool:
        return any(file_path.endswith(ext) for ext in self.supported_extensions)

    def extract(self, source: str, file_path: str = "") -> List[ASTEntity]:
        return self._extractor.extract(source)
