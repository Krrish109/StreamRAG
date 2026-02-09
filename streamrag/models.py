"""Core data structures for StreamRAG."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ASTEntity:
    """A code entity extracted from the AST."""
    entity_type: str  # 'function' | 'class' | 'variable' | 'import' | 'module_code'
    name: str  # scoped: "ClassName.method_name" for nested
    line_start: int  # 1-indexed
    line_end: int  # 1-indexed
    signature_hash: str  # SHA256[:12] of signature+body
    structure_hash: str  # SHA256[:12] of structure WITHOUT name
    calls: List[str] = field(default_factory=list)
    uses: List[str] = field(default_factory=list)
    inherits: List[str] = field(default_factory=list)
    imports: List[Tuple[str, str]] = field(default_factory=list)  # (module, name)
    type_refs: List[str] = field(default_factory=list)  # type annotation references
    type_context: Dict[str, str] = field(default_factory=dict)  # var_name -> type_name
    params: List[str] = field(default_factory=list)  # function parameter names (excluding self/cls)
    decorators: List[str] = field(default_factory=list)
    old_name: Optional[str] = None  # set during rename detection


@dataclass
class GraphNode:
    """A node in the code graph."""
    id: str  # SHA256("{file_path}:{entity_type}:{name}")[:16]
    type: str
    name: str
    file_path: str
    line_start: int
    line_end: int
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    """A directed edge in the code graph."""
    source_id: str
    target_id: str
    edge_type: str  # 'calls' | 'imports' | 'inherits' | 'uses' | 'uses_type' | 'defines' | 'decorated_by'
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CodeChange:
    """Represents a code change event."""
    file_path: str
    old_content: str  # FULL file content
    new_content: str  # FULL file content
    cursor_position: Tuple[int, int] = (0, 0)  # (line, column)
    change_type: str = "replace"  # 'insert' | 'delete' | 'replace'


@dataclass
class GraphOperation:
    """A graph mutation operation."""
    op_type: str  # 'add_node' | 'remove_node' | 'update_node'
    node_id: str
    node_type: str = ""
    properties: Dict[str, Any] = field(default_factory=dict)
    edges: List[Tuple[str, str]] = field(default_factory=list)  # [(target_id, edge_type)]


# Built-in names that should not be resolved as cross-file dependencies.
BUILTINS: frozenset = frozenset({
    # Keywords / constants
    "self", "cls", "None", "True", "False",
    # Built-in functions
    "print", "len", "range", "str", "int", "float", "bool", "list", "dict",
    "set", "tuple", "type", "isinstance", "issubclass", "super", "property",
    "staticmethod", "classmethod", "enumerate", "zip", "map", "filter",
    "sorted", "reversed", "any", "all", "min", "max", "sum", "abs",
    "open", "input", "repr", "hash", "id", "dir", "vars", "getattr",
    "setattr", "hasattr", "delattr", "callable", "iter", "next", "hex",
    "oct", "bin", "ord", "chr", "format", "round", "pow", "divmod",
    "object", "Exception", "ValueError", "TypeError", "KeyError",
    "IndexError", "AttributeError", "RuntimeError", "StopIteration",
    "NotImplementedError", "OSError", "IOError", "FileNotFoundError",
    "ImportError", "NameError", "ZeroDivisionError", "AssertionError",
    "breakpoint", "compile", "eval", "exec", "globals", "locals",
    "__import__", "__name__", "__file__", "__init__",
})

# Common method names on built-in types that create false cross-file edges.
COMMON_ATTR_METHODS: frozenset = frozenset({
    # dict/set/list methods
    "get", "set", "add", "pop", "push", "put",
    "append", "extend", "insert", "remove", "clear", "copy", "update",
    "keys", "values", "items", "setdefault",
    # string methods
    "format", "strip", "rstrip", "lstrip", "split", "join",
    "replace", "find", "index", "count", "startswith", "endswith",
    "encode", "decode", "lower", "upper", "title", "capitalize",
    # file/io methods
    "read", "write", "close", "flush", "seek",
    # sequence methods
    "sort", "reverse",
    # async/generator methods
    "send", "throw",
    # logging methods
    "debug", "info", "warning", "error", "critical", "exception",
    # HTTP/request methods
    "raise_for_status", "post", "patch", "delete", "head", "options",
    # DB/ORM methods
    "execute", "fetchone", "fetchall", "fetchmany", "commit", "rollback",
    "select", "where", "filter", "order_by", "group_by", "limit", "offset",
    "eq", "ne", "gt", "lt", "gte", "lte", "like", "ilike",
    "table", "upsert",
    # serialization methods
    "dumps", "loads", "model_dump", "model_validate", "dict", "json",
    # datetime methods
    "isoformat", "strftime", "strptime", "timestamp", "date", "time",
    "now", "utcnow", "today", "fromtimestamp", "fromisoformat",
    # testing methods
    "get_json", "assert_called", "assert_called_once", "assert_called_with",
    "assert_not_called", "assert_called_once_with",
    # path methods
    "exists", "mkdir", "rmdir", "unlink", "rename", "resolve",
    "is_file", "is_dir", "iterdir", "glob", "stat",
    # misc common methods
    "run", "start", "stop", "wait", "sleep", "acquire", "release",
    "match", "search", "sub", "findall",
    "invoke", "dispatch", "emit", "listen",
})

# Python standard library top-level module names.
# Calls through these (e.g. json.dumps, os.getenv) are filtered during extraction.
STDLIB_MODULES: frozenset = frozenset({
    "abc", "argparse", "array", "ast", "asyncio", "atexit",
    "base64", "binascii", "bisect", "builtins",
    "calendar", "cgi", "cgitb", "codecs", "collections", "colorsys",
    "compileall", "concurrent", "configparser", "contextlib", "contextvars",
    "copy", "copyreg", "csv", "ctypes", "curses",
    "dataclasses", "datetime", "dbm", "decimal", "difflib", "dis",
    "distutils", "doctest",
    "email", "encodings", "enum", "errno",
    "faulthandler", "fcntl", "filecmp", "fileinput", "fnmatch",
    "fractions", "ftplib", "functools",
    "gc", "getpass", "gettext", "glob", "grp", "gzip",
    "hashlib", "heapq", "hmac", "html", "http",
    "imaplib", "importlib", "inspect", "io", "ipaddress", "itertools",
    "json",
    "keyword",
    "linecache", "locale", "logging", "lzma",
    "mailbox", "math", "mimetypes", "mmap", "multiprocessing",
    "netrc", "numbers",
    "operator", "os", "ossaudiodev",
    "pathlib", "pdb", "pickle", "pickletools", "pipes", "pkgutil",
    "platform", "plistlib", "poplib", "posixpath", "pprint",
    "profile", "pstats", "pty", "pwd", "py_compile", "pydoc",
    "queue",
    "random", "re", "readline", "reprlib", "resource", "rlcompleter",
    "runpy",
    "sched", "secrets", "select", "selectors", "shelve", "shlex",
    "shutil", "signal", "site", "smtplib", "socket", "socketserver",
    "sqlite3", "ssl", "stat", "statistics", "string", "stringprep",
    "struct", "subprocess", "sunau", "symtable", "sys", "sysconfig",
    "syslog",
    "tabnanny", "tarfile", "tempfile", "termios", "test", "textwrap",
    "threading", "time", "timeit", "tkinter", "token", "tokenize",
    "tomllib", "trace", "traceback", "tracemalloc", "tty", "turtle",
    "types", "typing",
    "unicodedata", "unittest", "urllib", "uuid",
    "venv",
    "warnings", "wave", "weakref", "webbrowser",
    "xml", "xmlrpc",
    "zipfile", "zipimport", "zlib",
    # Common third-party that will never be in a project graph
    "_thread", "_io", "_collections_abc",
})

# Common third-party packages whose calls should never be counted as
# unresolved cross-file dependencies (they aren't in the project graph).
KNOWN_EXTERNAL_PACKAGES: frozenset = frozenset({
    "aiohttp", "aiofiles", "aiomysql", "aiopg", "aiosqlite",
    "anthropic", "anyio",
    "bcrypt", "beautifulsoup4", "boto3", "botocore",
    "celery", "certifi", "cffi", "charset_normalizer", "click",
    "cryptography",
    "databases", "django", "docker", "dotenv",
    "elasticsearch",
    "faker", "fastapi", "flask", "freezegun",
    "gevent", "google", "grpc", "gunicorn",
    "httpcore", "httpx",
    "jinja2",
    "kombu",
    "loguru",
    "marshmallow", "motor", "msgpack", "mypy",
    "numpy",
    "openai",
    "pandas", "paramiko", "pillow", "psycopg2", "pydantic",
    "pymongo", "pytest", "pytz",
    "redis", "requests", "respx", "rich", "ruff",
    "scipy", "sentry_sdk", "setuptools", "sklearn", "sniffio",
    "sqlalchemy", "starlette", "stripe", "supabase",
    "tenacity", "toml", "torch", "tortoise", "trio", "twilio",
    "ujson", "uvicorn", "uvloop",
    "websockets",
    "yaml",
})


# Patterns for framework/test methods that should be excluded from dead code detection.
FRAMEWORK_DEAD_CODE_PATTERNS = ("test_", "visit_", "setUp", "tearDown")

# All file extensions supported by the extractor registry.
# Single source of truth — used by hooks, bridge, and scripts.
SUPPORTED_EXTENSIONS = (
    ".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".rs", ".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".h",
    ".c", ".java",
)


def _is_test_file(path: str) -> bool:
    """Check if a file path looks like a test file.

    Multi-language patterns:
    - Python: test_*.py, *_test.py
    - JS/TS: *.test.ts, *.spec.ts, *.test.js, *.spec.js, *.test.tsx, *.spec.tsx
    - Rust: *_test.rs
    - Java: *Test.java, *Tests.java
    - C/C++: *_test.cpp, test_*.c, *_test.c, *_test.cc
    - All: files under tests/, test/, testing/, __tests__/, spec/ dirs
    """
    import os
    basename = os.path.basename(path)

    # Python patterns
    if basename.startswith("test_") or basename.endswith("_test.py"):
        return True
    # JS/TS patterns: *.test.ts, *.spec.ts, etc.
    for suffix in (".test.ts", ".spec.ts", ".test.tsx", ".spec.tsx",
                    ".test.js", ".spec.js", ".test.jsx", ".spec.jsx",
                    ".test.mjs", ".spec.mjs"):
        if basename.endswith(suffix):
            return True
    # Rust patterns
    if basename.endswith("_test.rs"):
        return True
    # Java patterns
    if basename.endswith(("Test.java", "Tests.java")):
        return True
    # C/C++ patterns
    for suffix in ("_test.cpp", "_test.cc", "_test.cxx", "_test.c",
                    "_test.hpp", "_test.h"):
        if basename.endswith(suffix):
            return True

    # Directory-based detection (all languages)
    parts = path.replace("\\", "/").split("/")
    return any(p in ("tests", "test", "testing", "__tests__", "spec") for p in parts)
