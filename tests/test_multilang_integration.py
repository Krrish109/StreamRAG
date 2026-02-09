"""End-to-end multi-language integration tests.

Each test creates a DeltaGraphBridge, feeds it a CodeChange with source code
in a specific language (file extension determines the extractor), and verifies
that graph nodes and edges are created correctly.
"""

import pytest

from streamrag.bridge import DeltaGraphBridge
from streamrag.models import CodeChange


@pytest.fixture
def bridge():
    return DeltaGraphBridge()


# ── Helpers ────────────────────────────────────────────────────────────────

def get_nodes_by_type(bridge, entity_type):
    """Return all graph nodes of a given entity_type."""
    return [n for n in bridge.graph._nodes.values() if n.type == entity_type]


def get_node_names(bridge, entity_type=None):
    """Return a set of node names, optionally filtered by type."""
    if entity_type:
        return {n.name for n in bridge.graph._nodes.values() if n.type == entity_type}
    return {n.name for n in bridge.graph._nodes.values()}


def get_edges_by_type(bridge, edge_type):
    """Return all edges of a given type across the entire graph."""
    edges = []
    for edge_list in bridge.graph._outgoing_edges.values():
        for e in edge_list:
            if e.edge_type == edge_type:
                edges.append(e)
    return edges


# ── 1. TypeScript function + class ─────────────────────────────────────────

def test_typescript_function_and_class(bridge):
    """TypeScript functions and classes produce nodes with correct types."""
    ts_code = """\
export function greet(name: string): string {
    return `Hello, ${name}`;
}

export class UserService {
    private name: string;

    constructor(name: string) {
        this.name = name;
    }

    getName(): string {
        return this.name;
    }
}
"""
    ops = bridge.process_change(CodeChange("service.ts", "", ts_code))
    assert len(ops) > 0, "Expected graph operations from TypeScript code"

    func_names = get_node_names(bridge, "function")
    class_names = get_node_names(bridge, "class")

    assert "greet" in func_names, f"Expected 'greet' function, got {func_names}"
    assert "UserService" in class_names, f"Expected 'UserService' class, got {class_names}"

    # Methods inside a class should be scoped: UserService.getName
    assert any("getName" in n for n in func_names), (
        f"Expected a method containing 'getName', got {func_names}"
    )


# ── 2. TypeScript imports ──────────────────────────────────────────────────

def test_typescript_imports(bridge):
    """TypeScript imports produce import nodes with edges to definitions."""
    # First, add a file that defines the exported entities
    source_code = """\
export class ApiClient {
    call(): void {}
}

export class UserModel {
    id: number;
}
"""
    bridge.process_change(CodeChange("api.ts", "", source_code))

    # Now add a file that imports from it
    consumer_code = """\
import { ApiClient, UserModel } from './api';

const client = new ApiClient();
"""
    ops = bridge.process_change(CodeChange("main.ts", "", consumer_code))
    assert len(ops) > 0

    import_names = get_node_names(bridge, "import")
    assert "ApiClient" in import_names, f"Expected 'ApiClient' import, got {import_names}"
    assert "UserModel" in import_names, f"Expected 'UserModel' import, got {import_names}"

    # Verify import edges exist (import node -> definition node)
    import_edges = get_edges_by_type(bridge, "imports")
    assert len(import_edges) > 0, "Expected at least one import edge"

    # Verify cross-file edge: import in main.ts should link to class in api.ts
    cross_file_import = False
    for edge in import_edges:
        src = bridge.graph.get_node(edge.source_id)
        tgt = bridge.graph.get_node(edge.target_id)
        if (src and tgt
                and src.file_path == "main.ts"
                and tgt.file_path == "api.ts"):
            cross_file_import = True
            break
    assert cross_file_import, "Expected a cross-file import edge from main.ts to api.ts"


# ── 3. JavaScript arrow function + class ───────────────────────────────────

def test_javascript_arrow_function_and_class(bridge):
    """JavaScript arrow functions and classes produce correct nodes."""
    js_code = """\
const calculate = (x, y) => {
    return x + y;
};

class EventEmitter {
    constructor() {
        this.handlers = {};
    }

    on(event, handler) {
        this.handlers[event] = handler;
    }
}

function processData(items) {
    return items.map(calculate);
}
"""
    ops = bridge.process_change(CodeChange("utils.js", "", js_code))
    assert len(ops) > 0, "Expected graph operations from JavaScript code"

    func_names = get_node_names(bridge, "function")
    class_names = get_node_names(bridge, "class")

    assert "calculate" in func_names, f"Expected 'calculate' arrow fn, got {func_names}"
    assert "processData" in func_names, f"Expected 'processData' function, got {func_names}"
    assert "EventEmitter" in class_names, f"Expected 'EventEmitter' class, got {class_names}"


# ── 4. Rust fn + struct + impl ─────────────────────────────────────────────

def test_rust_fn_struct_impl(bridge):
    """Rust fn, struct, and impl blocks produce correct nodes and edges."""
    rs_code = """\
pub struct Config {
    pub name: String,
    pub value: i32,
}

pub trait Validate {
    fn validate(&self) -> bool;
}

impl Validate for Config {
    fn validate(&self) -> bool {
        !self.name.is_empty()
    }
}

pub fn create_config(name: &str, value: i32) -> Config {
    Config { name: name.to_string(), value }
}
"""
    ops = bridge.process_change(CodeChange("config.rs", "", rs_code))
    assert len(ops) > 0, "Expected graph operations from Rust code"

    func_names = get_node_names(bridge, "function")
    class_names = get_node_names(bridge, "class")

    assert "create_config" in func_names, f"Expected 'create_config' fn, got {func_names}"
    assert "Config" in class_names, f"Expected 'Config' struct, got {class_names}"
    assert "Validate" in class_names, f"Expected 'Validate' trait, got {class_names}"

    # impl Validate for Config should appear as a class node with inherits edge
    # The impl block creates a node for Config (impl block) with an inherits
    # edge to Validate
    inherits_edges = get_edges_by_type(bridge, "inherits")
    assert len(inherits_edges) > 0, (
        "Expected at least one inherits edge from impl Validate for Config"
    )


# ── 5. Rust use imports ───────────────────────────────────────────────────

def test_rust_use_imports(bridge):
    """Rust use statements produce import nodes."""
    rs_code = """\
use crate::config::Config;
use crate::utils::{parse_input, validate};

pub fn process(cfg: Config) -> bool {
    let input = parse_input();
    validate(input)
}
"""
    ops = bridge.process_change(CodeChange("main.rs", "", rs_code))
    assert len(ops) > 0, "Expected graph operations from Rust use statements"

    import_names = get_node_names(bridge, "import")
    assert "Config" in import_names, f"Expected 'Config' import, got {import_names}"
    assert "parse_input" in import_names, f"Expected 'parse_input' import, got {import_names}"
    assert "validate" in import_names, f"Expected 'validate' import, got {import_names}"


# ── 6. C++ class with method ──────────────────────────────────────────────

def test_cpp_class_with_method(bridge):
    """C++ class and method produce correct nodes with scoped names."""
    cpp_code = """\
class Logger {
public:
    void log(const std::string& message) {
        std::cout << message << std::endl;
    }

    int getLevel() {
        return level;
    }

private:
    int level;
};

void initialize() {
    Logger logger;
}
"""
    ops = bridge.process_change(CodeChange("logger.cpp", "", cpp_code))
    assert len(ops) > 0, "Expected graph operations from C++ code"

    class_names = get_node_names(bridge, "class")
    func_names = get_node_names(bridge, "function")

    assert "Logger" in class_names, f"Expected 'Logger' class, got {class_names}"
    assert "initialize" in func_names, f"Expected 'initialize' function, got {func_names}"

    # Methods inside Logger should get scoped names
    scoped_methods = [n for n in func_names if "Logger." in n]
    assert len(scoped_methods) > 0, (
        f"Expected scoped methods like Logger.log, got {func_names}"
    )


# ── 7. C function + struct ────────────────────────────────────────────────

def test_c_function_and_struct(bridge):
    """C functions and structs produce correct node types."""
    c_code = """\
#include <stdio.h>
#include "myheader.h"

struct Point {
    int x;
    int y;
};

int compute_distance(struct Point a, struct Point b) {
    int dx = a.x - b.x;
    int dy = a.y - b.y;
    return dx * dx + dy * dy;
}

void print_point(struct Point p) {
    printf("(%d, %d)", p.x, p.y);
}
"""
    ops = bridge.process_change(CodeChange("geometry.c", "", c_code))
    assert len(ops) > 0, "Expected graph operations from C code"

    func_names = get_node_names(bridge, "function")
    class_names = get_node_names(bridge, "class")
    import_names = get_node_names(bridge, "import")

    assert "compute_distance" in func_names, f"Expected 'compute_distance', got {func_names}"
    assert "print_point" in func_names, f"Expected 'print_point', got {func_names}"
    assert "Point" in class_names, f"Expected 'Point' struct, got {class_names}"

    # #include "myheader.h" should produce an import node
    assert len(import_names) > 0, "Expected at least one import from #include"


# ── 8. Java class with method ─────────────────────────────────────────────

def test_java_class_with_method(bridge):
    """Java class and methods produce correct nodes with scoped names."""
    java_code = """\
public class UserRepository {
    private final String connectionUrl;

    public UserRepository(String url) {
        this.connectionUrl = url;
    }

    public User findById(int id) {
        return null;
    }

    public void save(User user) {
        return;
    }
}
"""
    ops = bridge.process_change(CodeChange("UserRepository.java", "", java_code))
    assert len(ops) > 0, "Expected graph operations from Java code"

    class_names = get_node_names(bridge, "class")
    func_names = get_node_names(bridge, "function")

    assert "UserRepository" in class_names, (
        f"Expected 'UserRepository' class, got {class_names}"
    )

    # Methods should be scoped under the class
    scoped_methods = [n for n in func_names if "UserRepository." in n]
    assert len(scoped_methods) > 0, (
        f"Expected scoped methods like UserRepository.findById, got {func_names}"
    )


# ── 9. Java import ────────────────────────────────────────────────────────

def test_java_import(bridge):
    """Java import statements produce import nodes."""
    java_code = """\
import java.util.List;
import com.example.service.UserService;

public class App {
    public void run() {
        UserService svc = new UserService();
    }
}
"""
    ops = bridge.process_change(CodeChange("App.java", "", java_code))
    assert len(ops) > 0, "Expected graph operations from Java import"

    import_names = get_node_names(bridge, "import")
    # java.util.List -> import name is "List"
    assert "List" in import_names, f"Expected 'List' import, got {import_names}"
    assert "UserService" in import_names, f"Expected 'UserService' import, got {import_names}"


# ── 10. Cross-language coexistence ─────────────────────────────────────────

def test_cross_language_python_and_typescript(bridge):
    """Python and TypeScript files can coexist in the same graph."""
    py_code = """\
def compute(x):
    return x * 2

class DataProcessor:
    def process(self, data):
        return compute(data)
"""
    ts_code = """\
export function transform(input: number): number {
    return input * 3;
}

export class DataTransformer {
    transform(data: number): number {
        return transform(data);
    }
}
"""
    bridge.process_change(CodeChange("processor.py", "", py_code))
    bridge.process_change(CodeChange("transformer.ts", "", ts_code))

    # Both languages should have nodes in the graph
    py_nodes = bridge.graph.get_nodes_by_file("processor.py")
    ts_nodes = bridge.graph.get_nodes_by_file("transformer.ts")

    assert len(py_nodes) > 0, "Expected nodes from Python file"
    assert len(ts_nodes) > 0, "Expected nodes from TypeScript file"

    py_names = {n.name for n in py_nodes}
    ts_names = {n.name for n in ts_nodes}

    assert "compute" in py_names, f"Expected 'compute' in Python nodes, got {py_names}"
    assert "DataProcessor" in py_names, (
        f"Expected 'DataProcessor' in Python nodes, got {py_names}"
    )
    assert "transform" in ts_names, (
        f"Expected 'transform' in TypeScript nodes, got {ts_names}"
    )
    assert "DataTransformer" in ts_names, (
        f"Expected 'DataTransformer' in TypeScript nodes, got {ts_names}"
    )

    # Total node count should include entities from both files
    total_nodes = bridge.graph.node_count
    assert total_nodes >= 4, (
        f"Expected at least 4 nodes (2 per file), got {total_nodes}"
    )

    # The graph should track file-level information for both
    all_files = set(bridge.graph._nodes_by_file.keys())
    assert "processor.py" in all_files, f"Expected processor.py in file index, got {all_files}"
    assert "transformer.ts" in all_files, (
        f"Expected transformer.ts in file index, got {all_files}"
    )
