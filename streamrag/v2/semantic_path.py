"""Semantic paths: fully qualified entity addressing with scope-aware extraction."""

import ast
import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from streamrag.models import ASTEntity


def _sha256_short(text: str, length: int = 16) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:length]


@dataclass(frozen=True)
class SemanticPath:
    """Fully qualified entity address."""
    file_path: str
    scope_chain: Tuple[str, ...]  # ('UserService', 'get_user') for nested
    entity_type: str
    name: str
    signature_hash: str
    line_start: int
    line_end: int

    @property
    def fqn(self) -> str:
        """Fully qualified name."""
        scope = "::".join(self.scope_chain) if self.scope_chain else ""
        return f"{self.file_path}::{scope}::{self.entity_type}::{self.name}"

    @property
    def unique_id(self) -> str:
        """Unique identifier based on FQN and signature."""
        return _sha256_short(f"{self.fqn}::{self.signature_hash}")

    @property
    def scope_depth(self) -> int:
        return len(self.scope_chain)


class ScopeAwareExtractor(ast.NodeVisitor):
    """Enhanced extractor that produces SemanticPath objects.

    Differences from V1 ASTExtractor:
    - Parameters extracted as first-class entities
    - Variables tracked at ALL scope levels (not just module-level)
    - Calls de-duplicated
    - Signature hash includes default count
    """

    def __init__(self, file_path: str = "") -> None:
        self._file_path = file_path
        self._scope_chain: List[str] = []
        self._paths: List[SemanticPath] = []

    def extract(self, source: str, file_path: str = "") -> List[SemanticPath]:
        """Extract all semantic paths from source."""
        fp = file_path or self._file_path
        if not source.strip():
            return []

        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []

        self._file_path = fp
        self._scope_chain = []
        self._paths = []
        self.visit(tree)
        return self._paths

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node) -> None:
        scope = tuple(self._scope_chain)
        args = [arg.arg for arg in node.args.args]
        defaults_count = len(node.args.defaults)
        sig = f"func({','.join(args)})[d={defaults_count}]"
        body_hash = hashlib.sha256(ast.dump(node).encode()).hexdigest()[:8]
        sig_hash = _sha256_short(f"{sig}|body:{body_hash}", 12)

        self._paths.append(SemanticPath(
            file_path=self._file_path,
            scope_chain=scope,
            entity_type="function",
            name=node.name,
            signature_hash=sig_hash,
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
        ))

        # Extract parameters as first-class entities
        for arg in node.args.args:
            param_scope = scope + (node.name,)
            self._paths.append(SemanticPath(
                file_path=self._file_path,
                scope_chain=param_scope,
                entity_type="parameter",
                name=arg.arg,
                signature_hash=_sha256_short(f"param:{arg.arg}", 12),
                line_start=node.lineno,
                line_end=node.lineno,
            ))

        self._scope_chain.append(node.name)
        self.generic_visit(node)
        self._scope_chain.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        scope = tuple(self._scope_chain)
        base_names = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                base_names.append(base.id)
        body_hash = hashlib.sha256(ast.dump(node).encode()).hexdigest()[:8]
        sig_hash = _sha256_short(f"class({','.join(base_names)})|body:{body_hash}", 12)

        self._paths.append(SemanticPath(
            file_path=self._file_path,
            scope_chain=scope,
            entity_type="class",
            name=node.name,
            signature_hash=sig_hash,
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
        ))

        self._scope_chain.append(node.name)
        self.generic_visit(node)
        self._scope_chain.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        """Variables tracked at ALL scope levels."""
        scope = tuple(self._scope_chain)
        for target in node.targets:
            if isinstance(target, ast.Name):
                self._paths.append(SemanticPath(
                    file_path=self._file_path,
                    scope_chain=scope,
                    entity_type="variable",
                    name=target.id,
                    signature_hash=_sha256_short(f"var:{target.id}|{ast.dump(node.value)}", 12),
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                ))

    def visit_Import(self, node: ast.Import) -> None:
        scope = tuple(self._scope_chain)
        for alias in node.names:
            name = alias.asname or alias.name
            self._paths.append(SemanticPath(
                file_path=self._file_path,
                scope_chain=scope,
                entity_type="import",
                name=name,
                signature_hash=_sha256_short(f"import:{ast.dump(node)}", 12),
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
            ))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        scope = tuple(self._scope_chain)
        for alias in (node.names or []):
            name = alias.asname or alias.name
            self._paths.append(SemanticPath(
                file_path=self._file_path,
                scope_chain=scope,
                entity_type="import",
                name=name,
                signature_hash=_sha256_short(f"import:{ast.dump(node)}", 12),
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
            ))


def find_entity_at_position(
    paths: List[SemanticPath], line: int
) -> Optional[SemanticPath]:
    """Return the deepest-nested entity containing the line."""
    candidates = [p for p in paths if p.line_start <= line <= p.line_end]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.scope_depth)


def resolve_name(
    name: str,
    scope_chain: Tuple[str, ...],
    paths: List[SemanticPath],
) -> Optional[SemanticPath]:
    """LEGB-like name resolution: search from innermost to outermost scope."""
    # Build scope levels from innermost to outermost
    for i in range(len(scope_chain), -1, -1):
        search_scope = scope_chain[:i]
        for path in paths:
            if path.name == name and path.scope_chain == search_scope:
                return path
    return None
