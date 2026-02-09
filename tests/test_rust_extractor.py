"""Tests for the Rust language extractor."""

import pytest

from streamrag.languages.rust import RustExtractor


@pytest.fixture
def ext():
    return RustExtractor()


# ── 1. can_handle ────────────────────────────────────────────────────────

def test_can_handle_rs(ext):
    assert ext.can_handle("main.rs") is True
    assert ext.can_handle("src/lib.rs") is True
    assert ext.can_handle("tests/integration_test.rs") is True


def test_can_handle_rejects_non_rs(ext):
    assert ext.can_handle("main.py") is False
    assert ext.can_handle("app.js") is False
    assert ext.can_handle("lib.ts") is False
    assert ext.can_handle("file.rsx") is False


# ── 2. language_id ───────────────────────────────────────────────────────

def test_language_id(ext):
    assert ext.language_id == "rust"


# ── 3. fn extraction (pub, async, unsafe) ────────────────────────────────

def test_fn_extraction_basic(ext):
    code = "fn main() {\n    println!(\"hello\");\n}\n"
    entities = ext.extract(code, "main.rs")
    fns = [e for e in entities if e.entity_type == "function"]
    assert len(fns) == 1
    assert fns[0].name == "main"


def test_fn_extraction_pub_async_unsafe(ext):
    code = (
        "pub fn public_fn() {}\n"
        "\n"
        "async fn async_fn() {}\n"
        "\n"
        "pub async fn pub_async_fn() {}\n"
        "\n"
        "unsafe fn unsafe_fn() {}\n"
        "\n"
        "pub unsafe fn pub_unsafe_fn() {}\n"
    )
    entities = ext.extract(code, "lib.rs")
    fn_names = sorted(e.name for e in entities if e.entity_type == "function")
    assert fn_names == ["async_fn", "pub_async_fn", "pub_unsafe_fn", "public_fn", "unsafe_fn"]


# ── 4. struct extraction ─────────────────────────────────────────────────

def test_struct_extraction(ext):
    code = (
        "pub struct User {\n"
        "    name: String,\n"
        "    age: u32,\n"
        "}\n"
        "\n"
        "struct Internal;\n"
    )
    entities = ext.extract(code, "models.rs")
    structs = [e for e in entities if e.entity_type == "class" and "struct" not in e.name.lower() or e.entity_type == "class"]
    struct_names = sorted(e.name for e in entities if e.entity_type == "class")
    assert "User" in struct_names
    assert "Internal" in struct_names


# ── 5. enum extraction ──────────────────────────────────────────────────

def test_enum_extraction(ext):
    code = (
        "pub enum Color {\n"
        "    Red,\n"
        "    Green,\n"
        "    Blue,\n"
        "}\n"
    )
    entities = ext.extract(code, "types.rs")
    enums = [e for e in entities if e.entity_type == "class" and e.name == "Color"]
    assert len(enums) == 1


# ── 6. trait extraction with supertraits ─────────────────────────────────

def test_trait_extraction_simple(ext):
    code = "pub trait Drawable {\n    fn draw(&self);\n}\n"
    entities = ext.extract(code, "traits.rs")
    traits = [e for e in entities if e.entity_type == "class" and e.name == "Drawable"]
    assert len(traits) == 1
    assert traits[0].inherits == []


def test_trait_extraction_with_supertraits(ext):
    code = "pub trait Clickable: Drawable + Sized {\n    fn on_click(&self);\n}\n"
    entities = ext.extract(code, "traits.rs")
    traits = [e for e in entities if e.entity_type == "class" and e.name == "Clickable"]
    assert len(traits) == 1
    # Sized is a Rust builtin, should be filtered; Drawable should remain
    assert "Drawable" in traits[0].inherits


# ── 7. impl block extraction ────────────────────────────────────────────

def test_impl_block_basic(ext):
    code = (
        "impl User {\n"
        "    fn new(name: String) -> Self {\n"
        "        User { name }\n"
        "    }\n"
        "}\n"
    )
    entities = ext.extract(code, "user.rs")
    impls = [e for e in entities if e.entity_type == "class" and e.name == "User"]
    assert len(impls) == 1


def test_impl_trait_for_struct(ext):
    code = (
        "impl Drawable for Circle {\n"
        "    fn draw(&self) {\n"
        "        render_circle(self);\n"
        "    }\n"
        "}\n"
    )
    entities = ext.extract(code, "impls.rs")
    impls = [e for e in entities if e.entity_type == "class" and e.name == "Circle"]
    assert len(impls) == 1
    assert impls[0].inherits == ["Drawable"]


# ── 8. type alias extraction ────────────────────────────────────────────

def test_type_alias_extraction(ext):
    code = "pub type Result<T> = std::result::Result<T, MyError>;\n"
    entities = ext.extract(code, "types.rs")
    # Type alias name starts uppercase, captured as variable
    aliases = [e for e in entities if e.entity_type == "variable" and e.name == "Result"]
    assert len(aliases) == 1


# ── 9. const/static extraction ──────────────────────────────────────────

def test_const_static_extraction(ext):
    code = (
        "const MAX_SIZE: usize = 1024;\n"
        "pub static GLOBAL_STATE: Mutex<State> = Mutex::new(State::default());\n"
    )
    entities = ext.extract(code, "config.rs")
    vars_ = [e for e in entities if e.entity_type == "variable"]
    var_names = sorted(e.name for e in vars_)
    assert "MAX_SIZE" in var_names
    assert "GLOBAL_STATE" in var_names


# ── 10. mod extraction ──────────────────────────────────────────────────

def test_mod_extraction(ext):
    code = (
        "pub mod handlers;\n"
        "mod utils;\n"
        "mod tests {\n"
        "    fn test_something() {}\n"
        "}\n"
    )
    entities = ext.extract(code, "lib.rs")
    mods = [e for e in entities if e.entity_type == "module_code"]
    mod_names = sorted(e.name for e in mods)
    assert "handlers" in mod_names
    assert "utils" in mod_names
    assert "tests" in mod_names


# ── 11. macro_rules! extraction ─────────────────────────────────────────

def test_macro_rules_extraction(ext):
    code = (
        "macro_rules! my_macro {\n"
        "    ($x:expr) => {\n"
        "        println!(\"{}\", $x);\n"
        "    };\n"
        "}\n"
    )
    entities = ext.extract(code, "macros.rs")
    macros = [e for e in entities if e.entity_type == "function" and e.name == "my_macro"]
    assert len(macros) == 1


# ── 12. use import extraction ───────────────────────────────────────────

def test_use_import_simple(ext):
    code = "use crate::models::User;\n"
    entities = ext.extract(code, "main.rs")
    imports = [e for e in entities if e.entity_type == "import"]
    assert len(imports) == 1
    assert imports[0].name == "User"
    assert imports[0].imports == [("models", "User")]


def test_use_import_braced(ext):
    code = "use crate::models::{User, Post, Comment};\n"
    entities = ext.extract(code, "main.rs")
    imports = [e for e in entities if e.entity_type == "import"]
    import_names = sorted(e.name for e in imports)
    assert import_names == ["Comment", "Post", "User"]


def test_use_import_glob(ext):
    code = "use crate::prelude::*;\n"
    entities = ext.extract(code, "main.rs")
    imports = [e for e in entities if e.entity_type == "import"]
    assert len(imports) == 1
    assert imports[0].name == "*"
    assert imports[0].imports == [("prelude", "*")]


def test_use_import_rename(ext):
    code = "use crate::models::User as AppUser;\n"
    entities = ext.extract(code, "main.rs")
    imports = [e for e in entities if e.entity_type == "import"]
    assert len(imports) == 1
    assert imports[0].name == "AppUser"


# ── 13. Attribute extraction as decorators ───────────────────────────────

def test_attribute_extraction_as_decorators(ext):
    code = (
        "#[derive(Debug, Clone)]\n"
        "#[serde(rename_all = \"camelCase\")]\n"
        "pub struct Config {\n"
        "    name: String,\n"
        "}\n"
    )
    entities = ext.extract(code, "config.rs")
    structs = [e for e in entities if e.entity_type == "class" and e.name == "Config"]
    assert len(structs) == 1
    assert "derive" in structs[0].decorators
    assert "serde" in structs[0].decorators


def test_attribute_on_function(ext):
    code = (
        "#[test]\n"
        "fn test_something() {\n"
        "    assert_eq!(1, 1);\n"
        "}\n"
    )
    entities = ext.extract(code, "tests.rs")
    fns = [e for e in entities if e.entity_type == "function" and e.name == "test_something"]
    assert len(fns) == 1
    assert "test" in fns[0].decorators


# ── 14. Call extraction with builtin filtering ───────────────────────────

def test_call_extraction_filters_builtins(ext):
    code = (
        "fn process() {\n"
        "    let v = Vec::new();\n"
        "    println!(\"hello\");\n"
        "    custom_handler(v);\n"
        "    another_call();\n"
        "}\n"
    )
    entities = ext.extract(code, "lib.rs")
    fns = [e for e in entities if e.entity_type == "function" and e.name == "process"]
    assert len(fns) == 1
    # custom_handler and another_call should be present; println and Vec::new filtered
    assert "custom_handler" in fns[0].calls
    assert "another_call" in fns[0].calls
    # Builtins should be filtered out
    assert "println" not in fns[0].calls


# ── 15. Nested functions in impl blocks get scoped names ─────────────────

def test_impl_methods_get_scoped_names(ext):
    code = (
        "impl Server {\n"
        "    pub fn start(&self) {\n"
        "        self.bind();\n"
        "    }\n"
        "\n"
        "    fn stop(&self) {\n"
        "        self.cleanup();\n"
        "    }\n"
        "}\n"
    )
    entities = ext.extract(code, "server.rs")
    fn_names = sorted(e.name for e in entities if e.entity_type == "function")
    # Methods inside impl Server should be scoped as Server.start, Server.stop
    assert "Server.start" in fn_names
    assert "Server.stop" in fn_names


# ── 16. Empty input returns [] ───────────────────────────────────────────

def test_empty_input_returns_empty(ext):
    assert ext.extract("", "empty.rs") == []
    assert ext.extract("   \n\n  ", "whitespace.rs") == []


# ── 17. Raw string stripping doesn't affect extraction ───────────────────

def test_raw_string_stripping(ext):
    """Ensure that function names inside raw strings are not extracted."""
    code = (
        'fn real_function() {\n'
        '    let s = r#"fn fake_function() {}"#;\n'
        '    let t = r"fn another_fake()";\n'
        '}\n'
    )
    entities = ext.extract(code, "raw.rs")
    fn_names = [e.name for e in entities if e.entity_type == "function"]
    assert "real_function" in fn_names
    # fake functions inside raw strings should NOT be extracted
    assert "fake_function" not in fn_names
    assert "another_fake" not in fn_names
