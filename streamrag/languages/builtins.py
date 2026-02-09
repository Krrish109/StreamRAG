"""Per-language builtin and common-method filter sets.

These sets are used by regex-based extractors to filter out language-native
names from call extraction, preventing false cross-file edges.
"""

# ── TypeScript / JavaScript ─────────────────────────────────────────────

TS_BUILTINS: frozenset = frozenset({
    # Global objects
    "console", "window", "document", "navigator", "location", "history",
    "Math", "JSON", "Date", "RegExp", "Error", "Symbol", "Proxy", "Reflect",
    # Constructors / types
    "Promise", "Array", "Map", "Set", "WeakMap", "WeakSet", "WeakRef",
    "Object", "Function", "Number", "String", "Boolean",
    "Int8Array", "Uint8Array", "Float32Array", "Float64Array",
    "ArrayBuffer", "SharedArrayBuffer", "DataView",
    "BigInt", "BigInt64Array", "BigUint64Array",
    # Global functions
    "parseInt", "parseFloat", "isNaN", "isFinite", "encodeURI",
    "decodeURI", "encodeURIComponent", "decodeURIComponent",
    "setTimeout", "setInterval", "clearTimeout", "clearInterval",
    "requestAnimationFrame", "cancelAnimationFrame",
    "fetch", "alert", "confirm", "prompt", "atob", "btoa",
    # Node.js globals
    "require", "module", "exports", "process", "Buffer", "global",
    "__dirname", "__filename",
    # Keywords / values
    "undefined", "null", "NaN", "Infinity", "this", "super",
    "true", "false", "void", "typeof", "instanceof", "new", "delete",
    # TypeScript-specific builtins
    "Record", "Partial", "Required", "Readonly", "Pick", "Omit",
    "Exclude", "Extract", "NonNullable", "ReturnType", "Parameters",
    "ConstructorParameters", "InstanceType", "ThisParameterType",
    "Awaited", "Uppercase", "Lowercase", "Capitalize", "Uncapitalize",
    "keyof", "infer", "extends", "implements",
})

TS_COMMON_METHODS: frozenset = frozenset({
    # Array methods
    "push", "pop", "shift", "unshift", "splice", "slice", "concat",
    "map", "filter", "reduce", "forEach", "find", "findIndex", "some",
    "every", "includes", "indexOf", "lastIndexOf", "flat", "flatMap",
    "sort", "reverse", "fill", "copyWithin", "entries", "keys", "values",
    # String methods
    "charAt", "charCodeAt", "split", "join", "replace", "replaceAll",
    "trim", "trimStart", "trimEnd", "padStart", "padEnd",
    "startsWith", "endsWith", "includes", "match", "search", "substring",
    "toLowerCase", "toUpperCase", "repeat", "normalize",
    # Object/Map/Set methods
    "hasOwnProperty", "toString", "valueOf", "toJSON",
    "get", "set", "has", "delete", "clear", "add", "size",
    # Promise methods
    "then", "catch", "finally", "all", "race", "allSettled", "any",
    "resolve", "reject",
    # Console methods
    "log", "warn", "error", "info", "debug", "trace", "table", "dir",
    # DOM methods
    "getElementById", "querySelector", "querySelectorAll",
    "addEventListener", "removeEventListener", "createElement",
    "appendChild", "removeChild", "setAttribute", "getAttribute",
    "classList", "style", "innerHTML", "textContent",
    # Event methods
    "preventDefault", "stopPropagation",
    # JSON methods
    "parse", "stringify",
    # Misc
    "bind", "call", "apply", "next", "return", "throw",
    "emit", "on", "once", "off",
})

# TypeScript type annotation builtins (filtered from type_refs)
TS_TYPE_BUILTINS: frozenset = frozenset({
    "string", "number", "boolean", "void", "any", "unknown", "never",
    "null", "undefined", "object", "symbol", "bigint",
    "Promise", "Array", "Map", "Set", "Record", "Partial", "Required",
    "Readonly", "Pick", "Omit", "Exclude", "Extract", "NonNullable",
    "ReturnType", "Parameters", "InstanceType", "Awaited",
    "Iterable", "Iterator", "AsyncIterable", "AsyncIterator",
    "Generator", "AsyncGenerator", "IterableIterator",
    "ReadonlyArray", "ReadonlyMap", "ReadonlySet",
    "Function", "Object", "Number", "String", "Boolean", "Error",
    "Date", "RegExp", "Symbol", "Buffer",
    "HTMLElement", "Element", "Node", "Event", "EventTarget",
    "JSX", "React", "ReactNode", "ReactElement",
    "T", "K", "V", "U", "P", "R",  # Common generic type params
})

# ── Rust ─────────────────────────────────────────────────────────────────

RUST_BUILTINS: frozenset = frozenset({
    # Macros
    "println", "eprintln", "print", "eprint", "dbg",
    "format", "write", "writeln",
    "vec", "panic", "todo", "unimplemented", "unreachable",
    "assert", "assert_eq", "assert_ne", "debug_assert",
    "cfg", "env", "include", "include_str", "include_bytes",
    "concat", "stringify", "line", "column", "file", "module_path",
    # Primitive types
    "bool", "char", "str", "i8", "i16", "i32", "i64", "i128", "isize",
    "u8", "u16", "u32", "u64", "u128", "usize", "f32", "f64",
    # Core types / prelude
    "Box", "Vec", "String", "Option", "Result",
    "Some", "None", "Ok", "Err",
    "Clone", "Copy", "Send", "Sync", "Sized", "Unpin",
    "Drop", "Default", "Debug", "Display",
    "Fn", "FnMut", "FnOnce",
    "Iterator", "IntoIterator", "ExactSizeIterator",
    "From", "Into", "TryFrom", "TryInto",
    "AsRef", "AsMut", "Borrow", "BorrowMut",
    "Eq", "PartialEq", "Ord", "PartialOrd", "Hash",
    "Add", "Sub", "Mul", "Div", "Rem", "Neg", "Not",
    "Deref", "DerefMut", "Index", "IndexMut",
    "Read", "Write", "Seek", "BufRead",
    "ToOwned", "ToString",
    # Keywords
    "self", "Self", "crate", "super", "pub", "mod",
    "let", "mut", "const", "static", "ref", "move",
    "async", "await", "unsafe", "extern", "dyn",
    "true", "false",
    # Std modules
    "std", "core", "alloc", "collections",
    "io", "fs", "path", "net", "sync", "thread",
    "fmt", "mem", "ptr", "ops", "iter", "num",
    "rc", "arc", "cell", "once",
    "HashMap", "HashSet", "BTreeMap", "BTreeSet", "VecDeque", "LinkedList",
    "Arc", "Rc", "Mutex", "RwLock", "Cell", "RefCell",
    "Pin", "Waker", "Future", "Poll",
    "Path", "PathBuf", "OsStr", "OsString",
    "Cow", "PhantomData",
})

RUST_COMMON_METHODS: frozenset = frozenset({
    "new", "default", "clone", "to_string", "to_owned",
    "unwrap", "expect", "unwrap_or", "unwrap_or_else", "unwrap_or_default",
    "is_some", "is_none", "is_ok", "is_err",
    "map", "and_then", "or_else", "map_err", "ok", "err",
    "as_ref", "as_mut", "as_str", "as_bytes", "as_slice",
    "into", "from", "try_into", "try_from",
    "iter", "into_iter", "iter_mut",
    "collect", "filter", "map", "fold", "for_each", "any", "all",
    "find", "position", "enumerate", "zip", "chain", "take", "skip",
    "len", "is_empty", "contains", "push", "pop", "insert", "remove",
    "get", "get_mut", "entry", "or_insert", "or_default",
    "read", "write", "flush", "close",
    "lock", "unlock", "try_lock",
    "fmt", "eq", "ne", "cmp", "partial_cmp", "hash",
    "with_capacity", "capacity", "reserve", "shrink_to_fit",
    "extend", "drain", "retain", "clear", "truncate",
    "join", "split", "trim", "starts_with", "ends_with", "replace",
    "borrow", "borrow_mut", "deref", "deref_mut",
    "display", "debug",
})

# ── C++ ──────────────────────────────────────────────────────────────────

CPP_BUILTINS: frozenset = frozenset({
    # I/O and streams
    "std", "cout", "cin", "cerr", "clog", "endl",
    "printf", "scanf", "fprintf", "fscanf", "sprintf", "snprintf",
    "puts", "gets", "getchar", "putchar",
    # Memory
    "malloc", "calloc", "realloc", "free", "new", "delete",
    "sizeof", "alignof", "offsetof",
    # Strings
    "string", "wstring", "to_string", "stoi", "stol", "stof", "stod",
    "strlen", "strcpy", "strncpy", "strcat", "strncat", "strcmp", "strncmp",
    "memcpy", "memmove", "memset", "memcmp",
    # Containers
    "vector", "map", "unordered_map", "set", "unordered_set",
    "list", "deque", "queue", "stack", "priority_queue",
    "array", "pair", "tuple", "optional", "variant", "any",
    # Smart pointers
    "shared_ptr", "unique_ptr", "weak_ptr", "make_shared", "make_unique",
    # Utility
    "move", "forward", "swap", "exchange",
    "min", "max", "abs", "sort", "find", "count",
    "begin", "end", "size", "empty",
    "static_cast", "dynamic_cast", "const_cast", "reinterpret_cast",
    # Types
    "int", "long", "short", "char", "float", "double", "bool", "void",
    "unsigned", "signed", "size_t", "ptrdiff_t", "nullptr", "NULL",
    "int8_t", "int16_t", "int32_t", "int64_t",
    "uint8_t", "uint16_t", "uint32_t", "uint64_t",
    "auto", "decltype", "constexpr",
    # Assert
    "assert", "static_assert",
    # Keywords
    "this", "true", "false", "class", "struct", "enum",
    "public", "private", "protected", "virtual", "override", "final",
    "const", "volatile", "mutable", "inline", "explicit",
    "namespace", "using", "typedef", "template", "typename",
    "try", "catch", "throw", "noexcept",
    # Exception types
    "exception", "runtime_error", "logic_error", "invalid_argument",
    "out_of_range", "overflow_error", "underflow_error",
    # Concurrency
    "thread", "mutex", "lock_guard", "unique_lock", "condition_variable",
    "atomic", "future", "promise", "async",
    # Algorithms/functional
    "function", "bind", "ref", "cref",
    "for_each", "transform", "accumulate", "reduce",
})

CPP_COMMON_METHODS: frozenset = frozenset({
    "push_back", "pop_back", "emplace_back", "emplace",
    "insert", "erase", "clear", "resize", "reserve",
    "front", "back", "at", "data",
    "begin", "end", "cbegin", "cend", "rbegin", "rend",
    "size", "empty", "capacity", "max_size",
    "find", "count", "contains", "lower_bound", "upper_bound",
    "first", "second", "get",
    "push", "pop", "top",
    "open", "close", "read", "write", "flush", "seekg", "seekp",
    "str", "c_str", "substr", "append", "replace", "compare",
    "length", "find", "rfind", "find_first_of", "find_last_of",
    "lock", "unlock", "try_lock",
    "wait", "notify_one", "notify_all",
    "load", "store", "exchange", "compare_exchange_strong",
    "reset", "release", "swap",
    "what", "code", "message",
})

# ── C ────────────────────────────────────────────────────────────────────

C_BUILTINS: frozenset = frozenset({
    # I/O
    "printf", "scanf", "fprintf", "fscanf", "sprintf", "snprintf",
    "puts", "gets", "getchar", "putchar", "fgets", "fputs",
    "fopen", "fclose", "fread", "fwrite", "fseek", "ftell", "rewind",
    "fflush", "feof", "ferror", "clearerr", "perror",
    # Memory
    "malloc", "calloc", "realloc", "free",
    "memcpy", "memmove", "memset", "memcmp",
    # Strings
    "strlen", "strcpy", "strncpy", "strcat", "strncat",
    "strcmp", "strncmp", "strchr", "strrchr", "strstr", "strtok",
    "atoi", "atol", "atof", "strtol", "strtoul", "strtod",
    # Utility
    "sizeof", "offsetof", "assert", "static_assert",
    "abs", "labs", "div", "ldiv",
    "rand", "srand", "time", "clock", "difftime",
    "exit", "abort", "atexit", "system", "getenv",
    "qsort", "bsearch",
    # Types / keywords
    "int", "long", "short", "char", "float", "double", "void",
    "unsigned", "signed", "const", "volatile", "static", "extern",
    "struct", "union", "enum", "typedef",
    "size_t", "ptrdiff_t", "NULL", "EOF",
    "int8_t", "int16_t", "int32_t", "int64_t",
    "uint8_t", "uint16_t", "uint32_t", "uint64_t",
    "bool", "true", "false",
    # Math
    "sin", "cos", "tan", "sqrt", "pow", "log", "exp", "floor", "ceil",
    "fabs", "fmod",
})

C_COMMON_METHODS: frozenset = frozenset()  # C has no methods

# ── Java ─────────────────────────────────────────────────────────────────

JAVA_BUILTINS: frozenset = frozenset({
    # Core classes
    "System", "String", "Integer", "Long", "Double", "Float",
    "Boolean", "Character", "Byte", "Short",
    "Object", "Class", "Enum",
    "Math", "StrictMath",
    "Thread", "Runnable",
    # Collections
    "Collections", "Arrays",
    "List", "ArrayList", "LinkedList",
    "Map", "HashMap", "TreeMap", "LinkedHashMap", "ConcurrentHashMap",
    "Set", "HashSet", "TreeSet", "LinkedHashSet",
    "Queue", "Deque", "ArrayDeque", "PriorityQueue",
    "Stack", "Vector",
    # Modern Java
    "Optional", "Stream", "Collectors",
    "CompletableFuture", "Future",
    "Consumer", "Supplier", "Function", "Predicate", "BiFunction",
    # I/O
    "File", "Path", "Paths", "Files",
    "InputStream", "OutputStream", "Reader", "Writer",
    "BufferedReader", "BufferedWriter", "PrintWriter",
    "Scanner",
    # Exceptions
    "Exception", "RuntimeException", "Error",
    "NullPointerException", "IllegalArgumentException",
    "IllegalStateException", "UnsupportedOperationException",
    "IndexOutOfBoundsException", "ClassNotFoundException",
    "IOException", "FileNotFoundException",
    # Annotations
    "Override", "Deprecated", "SuppressWarnings", "FunctionalInterface",
    # Keywords / values
    "this", "super", "null", "true", "false",
    "void", "int", "long", "double", "float", "boolean", "char", "byte", "short",
    # Common imports
    "var",
})

JAVA_COMMON_METHODS: frozenset = frozenset({
    # Object methods
    "toString", "equals", "hashCode", "getClass", "clone", "finalize",
    "wait", "notify", "notifyAll", "compareTo",
    # Collection methods
    "add", "remove", "get", "set", "put", "contains", "containsKey",
    "containsValue", "size", "isEmpty", "clear", "iterator",
    "toArray", "addAll", "removeAll", "retainAll",
    "keySet", "values", "entrySet",
    # Stream methods
    "stream", "parallelStream", "of", "map", "filter", "reduce",
    "collect", "forEach", "flatMap", "sorted", "distinct",
    "limit", "skip", "count", "findFirst", "findAny",
    "anyMatch", "allMatch", "noneMatch",
    "toList", "toSet", "toMap", "joining", "groupingBy",
    # String methods
    "length", "charAt", "substring", "indexOf", "lastIndexOf",
    "trim", "strip", "split", "replace", "replaceAll",
    "startsWith", "endsWith", "contains", "matches",
    "toLowerCase", "toUpperCase", "format", "valueOf",
    # Optional methods
    "isPresent", "isEmpty", "orElse", "orElseGet", "orElseThrow",
    "ifPresent", "ifPresentOrElse",
    # I/O methods
    "read", "write", "close", "flush", "print", "println",
    "readLine", "append", "delete",
    # Builder / getter / setter patterns
    "build", "builder",
    # Logging
    "info", "debug", "warn", "error", "trace",
    # Misc
    "run", "start", "stop", "execute", "call",
    "getName", "setName", "getType", "getId",
})
