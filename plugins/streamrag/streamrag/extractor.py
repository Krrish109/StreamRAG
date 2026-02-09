"""AST extraction and hashing for Python source code."""

import ast
import hashlib
from typing import List, Optional

from streamrag.models import ASTEntity, BUILTINS, COMMON_ATTR_METHODS, KNOWN_EXTERNAL_PACKAGES, STDLIB_MODULES


def _sha256_short(text: str, length: int = 12) -> str:
    """Compute SHA256 and return first `length` hex chars."""
    return hashlib.sha256(text.encode()).hexdigest()[:length]


class ASTExtractor(ast.NodeVisitor):
    """Extract code entities from Python source using the AST.

    Handles: FunctionDef, AsyncFunctionDef, ClassDef, module-level Assign,
    Import/ImportFrom, and module-level Expr(Call) as synthetic __module__.
    """

    def __init__(self) -> None:
        self._current_scope: List[str] = []
        self._entities: List[ASTEntity] = []
        self._stdlib_names: set = set()
        self._type_context: dict = {}

    def extract(self, source: str) -> List[ASTEntity]:
        """Extract all entities from Python source code.

        Returns empty list on empty content or SyntaxError.
        """
        if not source.strip():
            return []

        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []

        self._current_scope = []
        self._entities = []
        self._stdlib_names = self._collect_stdlib_imports(tree)
        self._external_type_names = self._collect_external_type_names(tree)
        self._type_context = {}
        self._module_type_context: dict = self._collect_module_type_context(tree)
        self.visit(tree)
        self._extract_module_calls(tree)
        return self._entities

    @staticmethod
    def _collect_stdlib_imports(tree: ast.Module) -> set:
        """Pre-pass: collect names imported from stdlib or external packages."""
        stdlib_names: set = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in STDLIB_MODULES or top in KNOWN_EXTERNAL_PACKAGES:
                        stdlib_names.add(alias.asname or alias.name)
            elif isinstance(node, ast.ImportFrom):
                top = (node.module or "").split(".")[0]
                if top in STDLIB_MODULES or top in KNOWN_EXTERNAL_PACKAGES:
                    for alias in (node.names or []):
                        stdlib_names.add(alias.asname or alias.name)
        return stdlib_names

    @staticmethod
    def _collect_external_type_names(tree: ast.Module) -> set:
        """Pre-pass: collect PascalCase names imported from external packages.

        e.g. `from httpx import AsyncClient` → {"AsyncClient"}
        These are used to filter out method calls on external types.
        """
        external_types: set = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                top = (node.module or "").split(".")[0]
                if top in KNOWN_EXTERNAL_PACKAGES:
                    for alias in (node.names or []):
                        name = alias.asname or alias.name
                        if name and name[0].isupper():
                            external_types.add(name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in KNOWN_EXTERNAL_PACKAGES:
                        name = alias.asname or alias.name
                        if name and name[0].isupper():
                            external_types.add(name)
        return external_types

    @staticmethod
    def _collect_module_type_context(tree: ast.Module) -> dict:
        """Pre-pass: collect module-level variable-to-type mappings.

        Sources:
        - `x = SomeClass()` at module level → {"x": "SomeClass"}
        - `x = module.SomeClass()` at module level → {"x": "SomeClass"}
        - `x: SomeClass = ...` at module level → {"x": "SomeClass"}
        """
        type_map: dict = {}
        for stmt in tree.body:
            if isinstance(stmt, ast.Assign):
                if (isinstance(stmt.value, ast.Call)
                        and isinstance(stmt.value.func, ast.Name)):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            type_map[target.id] = stmt.value.func.id
                elif (isinstance(stmt.value, ast.Call)
                      and isinstance(stmt.value.func, ast.Attribute)):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            type_map[target.id] = stmt.value.func.attr
            elif isinstance(stmt, ast.AnnAssign):
                if (isinstance(stmt.target, ast.Name)
                        and isinstance(stmt.annotation, ast.Name)):
                    type_map[stmt.target.id] = stmt.annotation.id
        return type_map

    def _scoped_name(self, name: str) -> str:
        """Build scoped name like 'ClassName.method_name'."""
        if self._current_scope:
            return ".".join(self._current_scope) + "." + name
        return name

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node) -> None:
        """Handle both sync and async function definitions."""
        name = self._scoped_name(node.name)
        type_ctx = self._extract_type_context(node)
        old_ctx = self._type_context
        self._type_context = type_ctx
        params = [arg.arg for arg in node.args.args if arg.arg not in ("self", "cls")]
        self._entities.append(ASTEntity(
            entity_type="function",
            name=name,
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            signature_hash=self._compute_signature_hash(node, "function"),
            structure_hash=self._compute_structure_hash(node, "function"),
            calls=self._extract_calls(node),
            uses=self._extract_uses(node),
            inherits=[],
            imports=[],
            type_refs=self._extract_type_refs(node),
            type_context=type_ctx,
            params=params,
            decorators=self._extract_decorators(node),
        ))
        self._type_context = old_ctx
        # Visit nested definitions
        self._current_scope.append(node.name)
        self.generic_visit(node)
        self._current_scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        name = self._scoped_name(node.name)
        base_names = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                base_names.append(base.id)
            elif isinstance(base, ast.Attribute):
                base_names.append(base.attr)

        self._entities.append(ASTEntity(
            entity_type="class",
            name=name,
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            signature_hash=self._compute_signature_hash(node, "class"),
            structure_hash=self._compute_structure_hash(node, "class"),
            calls=self._extract_calls(node),
            uses=self._extract_uses(node),
            inherits=base_names,
            imports=[],
            decorators=self._extract_decorators(node),
        ))
        # Visit nested definitions
        self._current_scope.append(node.name)
        self.generic_visit(node)
        self._current_scope.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        """Only extract module-level assignments."""
        if self._current_scope:
            return

        target_names = []
        for target in node.targets:
            if isinstance(target, ast.Name):
                target_names.append(target.id)
            elif isinstance(target, ast.Tuple):
                for elt in target.elts:
                    if isinstance(elt, ast.Name):
                        target_names.append(elt.id)

        if not target_names:
            return

        name = ", ".join(target_names)
        sig = f"var:{name}|{ast.dump(node.value)}"

        # Extract __all__ export names
        uses = self._extract_uses(node)
        if name == "__all__" and isinstance(node.value, (ast.List, ast.Tuple)):
            export_names = []
            for elt in node.value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    export_names.append(elt.value)
            uses = export_names

        self._entities.append(ASTEntity(
            entity_type="variable",
            name=name,
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            signature_hash=_sha256_short(sig),
            structure_hash=_sha256_short(f"other:{type(node).__name__}"),
            calls=[],
            uses=uses,
            inherits=[],
            imports=[],
        ))

    def visit_Import(self, node: ast.Import) -> None:
        """One entity per imported name."""
        sig = f"import:{ast.dump(node)}"
        sig_hash = _sha256_short(sig)
        struct_hash = _sha256_short(f"other:{type(node).__name__}")

        for alias in node.names:
            imported_name = alias.asname or alias.name
            self._entities.append(ASTEntity(
                entity_type="import",
                name=imported_name,
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                signature_hash=sig_hash,
                structure_hash=struct_hash,
                calls=[],
                uses=[],
                inherits=[],
                imports=[("", alias.name)],
            ))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """One entity per imported name."""
        sig = f"import:{ast.dump(node)}"
        sig_hash = _sha256_short(sig)
        struct_hash = _sha256_short(f"other:{type(node).__name__}")
        module = node.module or ""

        for alias in (node.names or []):
            imported_name = alias.asname or alias.name
            self._entities.append(ASTEntity(
                entity_type="import",
                name=imported_name,
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                signature_hash=sig_hash,
                structure_hash=struct_hash,
                calls=[],
                uses=[],
                inherits=[],
                imports=[(module, alias.name)],
            ))

    def _extract_module_calls(self, tree: ast.Module) -> None:
        """Create synthetic __module__ entity for module-level calls."""
        module_calls = []
        for stmt in tree.body:
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                call = stmt.value
                if isinstance(call.func, ast.Name):
                    name = call.func.id
                    if name not in BUILTINS and name not in self._stdlib_names:
                        module_calls.append(name)
                elif isinstance(call.func, ast.Attribute):
                    bare = call.func.attr
                    receiver = None
                    if isinstance(call.func.value, ast.Name):
                        receiver = call.func.value.id
                    if receiver and receiver in self._stdlib_names:
                        continue
                    if bare not in BUILTINS and bare not in COMMON_ATTR_METHODS:
                        module_calls.append(bare)

        if module_calls:
            self._entities.append(ASTEntity(
                entity_type="module_code",
                name="__module__",
                line_start=1,
                line_end=1,
                signature_hash="module",
                structure_hash="module",
                calls=module_calls,
                uses=[],
                inherits=[],
                imports=[],
            ))

    # Type annotation names to ignore (builtins and typing constructs)
    _TYPE_BUILTINS = frozenset({
        "str", "int", "float", "bool", "list", "dict", "set", "tuple",
        "None", "bytes", "complex", "object", "type",
        "Any", "Optional", "List", "Dict", "Set", "Tuple", "Union", "Type",
        "Callable", "Iterator", "Generator", "Sequence", "Mapping",
        "FrozenSet", "Deque", "DefaultDict", "OrderedDict", "Counter",
        "ClassVar", "Final", "Literal", "TypeVar", "Protocol",
    })

    @staticmethod
    def _extract_type_refs(node) -> List[str]:
        """Extract type annotation references from function parameters and return type."""
        refs = []
        seen = set()

        def _collect_names(ann_node):
            if ann_node is None:
                return
            if isinstance(ann_node, ast.Name):
                if ann_node.id not in ASTExtractor._TYPE_BUILTINS and ann_node.id not in seen:
                    seen.add(ann_node.id)
                    refs.append(ann_node.id)
            elif isinstance(ann_node, ast.Attribute):
                if ann_node.attr not in ASTExtractor._TYPE_BUILTINS and ann_node.attr not in seen:
                    seen.add(ann_node.attr)
                    refs.append(ann_node.attr)
            elif isinstance(ann_node, ast.Subscript):
                _collect_names(ann_node.value)
                _collect_names(ann_node.slice)
            elif isinstance(ann_node, ast.Tuple):
                for elt in ann_node.elts:
                    _collect_names(elt)
            elif isinstance(ann_node, ast.BinOp):
                # Handle X | Y union syntax (Python 3.10+)
                _collect_names(ann_node.left)
                _collect_names(ann_node.right)

        # Parameter annotations
        args = getattr(node, 'args', None)
        if args and hasattr(args, 'args'):
            for arg in args.args:
                _collect_names(arg.annotation)
            for arg in getattr(args, 'posonlyargs', []):
                _collect_names(arg.annotation)
            for arg in args.kwonlyargs:
                _collect_names(arg.annotation)
            if args.vararg:
                _collect_names(args.vararg.annotation)
            if args.kwarg:
                _collect_names(args.kwarg.annotation)

        # Return annotation
        _collect_names(getattr(node, 'returns', None))

        return refs

    @staticmethod
    def _extract_decorators(node) -> List[str]:
        """Extract decorator names from a function or class node."""
        decorators = []
        for dec in getattr(node, "decorator_list", []):
            if isinstance(dec, ast.Name):
                decorators.append(dec.id)
            elif isinstance(dec, ast.Attribute):
                parts = []
                current = dec
                while isinstance(current, ast.Attribute):
                    parts.append(current.attr)
                    current = current.value
                if isinstance(current, ast.Name):
                    parts.append(current.id)
                decorators.append(".".join(reversed(parts)))
            elif isinstance(dec, ast.Call):
                func = dec.func
                if isinstance(func, ast.Name):
                    decorators.append(func.id)
                elif isinstance(func, ast.Attribute):
                    parts = []
                    current = func
                    while isinstance(current, ast.Attribute):
                        parts.append(current.attr)
                        current = current.value
                    if isinstance(current, ast.Name):
                        parts.append(current.id)
                    decorators.append(".".join(reversed(parts)))
        return decorators

    @staticmethod
    def _compute_signature_hash(node, entity_type: str) -> str:
        """Compute signature hash that includes the body (detects ANY change)."""
        if entity_type == "function":
            args = ",".join(arg.arg for arg in node.args.args)
            sig = f"func:{node.name}({args})"
            sig += f"|body:{_sha256_short(ast.dump(node), 8)}"
            return _sha256_short(sig)

        if entity_type == "class":
            base_names = []
            for base in node.bases:
                if isinstance(base, ast.Name):
                    base_names.append(base.id)
                elif isinstance(base, ast.Attribute):
                    base_names.append(base.attr)
            sig = f"class:{node.name}({','.join(base_names)})"
            sig += f"|body:{_sha256_short(ast.dump(node), 8)}"
            return _sha256_short(sig)

        return _sha256_short(f"other:{ast.dump(node)}")

    @staticmethod
    def _compute_structure_hash(node, entity_type: str) -> str:
        """Compute structure hash WITHOUT the name (enables rename detection)."""
        if entity_type == "function":
            arg_names = [arg.arg for arg in node.args.args]
            stmt_types = [type(stmt).__name__ for stmt in node.body]
            sig = f"func_struct:({','.join(arg_names)})|{stmt_types}"
            return _sha256_short(sig)

        if entity_type == "class":
            stmt_types = [type(stmt).__name__ for stmt in node.body]
            sig = f"class_struct:|{stmt_types}"
            return _sha256_short(sig)

        return _sha256_short(f"other:{type(node).__name__}")

    @staticmethod
    def _extract_type_context(node) -> dict:
        """Extract variable-to-type mappings from annotations and assignments.

        Sources:
        - Parameter annotations: def foo(x: SomeClass) -> {"x": "SomeClass"}
        - Constructor assignments: x = SomeClass() -> {"x": "SomeClass"}
        - Annotated assignments: x: SomeClass = ... -> {"x": "SomeClass"}
        """
        type_map: dict = {}
        # Parameter annotations
        args_node = getattr(node, "args", None)
        for arg in (args_node.args if args_node else []):
            if arg.annotation:
                if isinstance(arg.annotation, ast.Name):
                    if arg.arg not in ("self", "cls"):
                        type_map[arg.arg] = arg.annotation.id
                elif isinstance(arg.annotation, ast.Attribute):
                    if arg.arg not in ("self", "cls"):
                        type_map[arg.arg] = arg.annotation.attr
        # Constructor assignments: x = SomeClass()
        for child in ast.walk(node):
            if isinstance(child, ast.Assign):
                if (isinstance(child.value, ast.Call)
                        and isinstance(child.value.func, ast.Name)):
                    for target in child.targets:
                        if isinstance(target, ast.Name):
                            type_map[target.id] = child.value.func.id
            # Annotated assignments: x: SomeClass = ...
            elif isinstance(child, ast.AnnAssign):
                if (isinstance(child.target, ast.Name)
                        and isinstance(child.annotation, ast.Name)):
                    type_map[child.target.id] = child.annotation.id
        return type_map

    def _extract_calls(self, node) -> List[str]:
        """Extract function calls within an AST subtree.

        For self.method()/cls.method() inside a class, emits qualified
        "ClassName.method" instead of bare "method".
        Filters out BUILTINS, COMMON_ATTR_METHODS, and stdlib imports.
        Uses type context to emit qualified names for typed receivers.
        """
        calls = []
        # Enclosing class for self/cls resolution (last scope element)
        enclosing_class = self._current_scope[-1] if self._current_scope else None

        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name):
                    name = child.func.id
                    if name not in BUILTINS and name not in self._stdlib_names:
                        calls.append(name)
                elif isinstance(child.func, ast.Attribute):
                    bare = child.func.attr
                    receiver = None
                    if isinstance(child.func.value, ast.Name):
                        receiver = child.func.value.id

                    if receiver in ("self", "cls") and enclosing_class:
                        # self.bar() inside class Foo -> "Foo.bar"
                        calls.append(f"{enclosing_class}.{bare}")
                    elif receiver and receiver in self._stdlib_names:
                        # Skip stdlib calls: json.dumps(), os.path.join(), etc.
                        continue
                    elif receiver and receiver in self._type_context:
                        # Type-qualified: always emit even for COMMON_ATTR_METHODS
                        # (type context makes the edge precise, not noisy)
                        class_name = self._type_context[receiver]
                        if class_name in self._external_type_names:
                            continue  # Skip external library type methods
                        calls.append(f"{class_name}.{bare}")
                    elif receiver and receiver in self._module_type_context:
                        # Module-level type context: x = SomeClass() → x.method()
                        class_name = self._module_type_context[receiver]
                        if class_name in self._external_type_names:
                            continue
                        calls.append(f"{class_name}.{bare}")
                    elif bare not in BUILTINS and bare not in COMMON_ATTR_METHODS:
                        if receiver and receiver not in BUILTINS:
                            calls.append(f"{receiver}.{bare}")
                        else:
                            # Bare function call via unknown receiver — add
                            # unqualified name only when there's no receiver
                            calls.append(bare)
        return calls

    @staticmethod
    def _extract_uses(node) -> List[str]:
        """Extract all Name references with Load context."""
        uses = []
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                uses.append(child.id)
        return uses


def extract(source: str) -> List[ASTEntity]:
    """Module-level convenience function for extraction."""
    return ASTExtractor().extract(source)
