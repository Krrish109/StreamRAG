"""JavaScript language extractor — thin subclass of TypeScript.

Removes TypeScript-specific patterns (interfaces, enums, type aliases)
and type annotation extraction. Shares all JS-compatible patterns.
"""

import re
from typing import Dict, List

from streamrag.languages.typescript import TypeScriptExtractor


class JavaScriptExtractor(TypeScriptExtractor):
    """Extract code entities from JavaScript/JSX source."""

    @property
    def language_id(self) -> str:
        return "javascript"

    @property
    def supported_extensions(self) -> List[str]:
        return [".js", ".jsx", ".mjs", ".cjs"]

    def can_handle(self, file_path: str) -> bool:
        return any(file_path.endswith(ext) for ext in self.supported_extensions)

    def _get_declaration_patterns(self) -> Dict[str, List[re.Pattern]]:
        """JS patterns: functions, classes, arrow functions, methods.

        No interfaces, enums, or type aliases.
        """
        return {
            "function": [self._FUNC_PATTERN, self._ARROW_PATTERN, self._METHOD_PATTERN],
            "class": [self._CLASS_PATTERN],
        }

    def _extract_type_refs_from_text(self, text: str) -> List[str]:
        """No type annotations in plain JavaScript."""
        return []
