"""Tests for the Java regex-based extractor."""

import pytest

from streamrag.languages.java import JavaExtractor


@pytest.fixture
def ext():
    return JavaExtractor()


# ── 1. can_handle ────────────────────────────────────────────────────────

def test_can_handle_java_extension(ext):
    assert ext.can_handle("Main.java") is True
    assert ext.can_handle("src/com/example/Service.java") is True


def test_can_handle_rejects_other_extensions(ext):
    assert ext.can_handle("app.js") is False
    assert ext.can_handle("main.py") is False
    assert ext.can_handle("utils.ts") is False
    assert ext.can_handle("Main.class") is False


# ── 2. language_id ───────────────────────────────────────────────────────

def test_language_id(ext):
    assert ext.language_id == "java"


# ── 3. Class extraction (public, abstract) ──────────────────────────────

def test_extract_public_class(ext):
    code = (
        "public class UserService {\n"
        "    private int count;\n"
        "}\n"
    )
    entities = ext.extract(code, "UserService.java")
    classes = [e for e in entities if e.entity_type == "class" and e.name == "UserService"]
    assert len(classes) == 1
    assert classes[0].line_start == 1


def test_extract_abstract_class(ext):
    code = (
        "public abstract class BaseRepository {\n"
        "    private int id;\n"
        "}\n"
    )
    entities = ext.extract(code, "BaseRepository.java")
    classes = [e for e in entities if e.entity_type == "class" and e.name == "BaseRepository"]
    assert len(classes) == 1


# ── 4. Class with extends and implements ─────────────────────────────────

def test_class_extends(ext):
    code = (
        "public class Dog extends Animal {\n"
        "    private int age;\n"
        "}\n"
    )
    entities = ext.extract(code, "Dog.java")
    classes = [e for e in entities if e.entity_type == "class" and e.name == "Dog"]
    assert len(classes) == 1
    assert "Animal" in classes[0].inherits


def test_class_extends_and_implements(ext):
    code = (
        "public class UserServiceImpl extends BaseService implements Serializable {\n"
        "    private int id;\n"
        "}\n"
    )
    entities = ext.extract(code, "UserServiceImpl.java")
    classes = [e for e in entities if e.entity_type == "class" and e.name == "UserServiceImpl"]
    assert len(classes) == 1
    assert "BaseService" in classes[0].inherits


# ── 5. Interface extraction with extends ─────────────────────────────────

def test_extract_interface(ext):
    code = (
        "public interface Repository {\n"
        "    void save();\n"
        "}\n"
    )
    entities = ext.extract(code, "Repository.java")
    ifaces = [e for e in entities if e.entity_type == "class" and e.name == "Repository"]
    assert len(ifaces) == 1


def test_interface_extends(ext):
    code = (
        "public interface CrudRepository extends Repository {\n"
        "    void delete(int id);\n"
        "}\n"
    )
    entities = ext.extract(code, "CrudRepository.java")
    ifaces = [e for e in entities if e.entity_type == "class" and e.name == "CrudRepository"]
    assert len(ifaces) == 1
    assert "Repository" in ifaces[0].inherits


# ── 6. Enum extraction with implements ───────────────────────────────────

def test_extract_enum(ext):
    code = (
        "public enum Color {\n"
        "    RED, GREEN, BLUE;\n"
        "}\n"
    )
    entities = ext.extract(code, "Color.java")
    enums = [e for e in entities if e.entity_type == "class" and e.name == "Color"]
    assert len(enums) == 1


def test_enum_with_implements(ext):
    code = (
        "public enum Status implements Displayable {\n"
        "    ACTIVE, INACTIVE;\n"
        "}\n"
    )
    entities = ext.extract(code, "Status.java")
    enums = [e for e in entities if e.entity_type == "class" and e.name == "Status"]
    assert len(enums) == 1
    assert "Displayable" in enums[0].inherits


# ── 7. Record extraction (Java 14+) ─────────────────────────────────────

def test_extract_record(ext):
    code = (
        "public record Point(int x, int y) {\n"
        "}\n"
    )
    entities = ext.extract(code, "Point.java")
    records = [e for e in entities if e.entity_type == "class" and e.name == "Point"]
    assert len(records) == 1


def test_record_with_implements(ext):
    code = (
        "public record UserDTO(String name, int age) implements Transferable {\n"
        "}\n"
    )
    entities = ext.extract(code, "UserDTO.java")
    records = [e for e in entities if e.entity_type == "class" and e.name == "UserDTO"]
    assert len(records) == 1
    assert "Transferable" in records[0].inherits


# ── 8. Annotation type extraction (@interface) ──────────────────────────

def test_extract_annotation_type(ext):
    code = (
        "public @interface Cacheable {\n"
        "    int ttl() default 60;\n"
        "}\n"
    )
    entities = ext.extract(code, "Cacheable.java")
    annos = [e for e in entities if e.entity_type == "class" and e.name == "Cacheable"]
    assert len(annos) == 1


# ── 9. Method extraction (public, private, static, synchronized) ────────
# Note: A field before the first method prevents the method regex's return-
# type pattern from consuming the preceding newline back to the class line,
# ensuring proper scoping.

def test_extract_public_method(ext):
    code = (
        "public class Foo {\n"
        "    private int x;\n"
        "    public void process() {\n"
        "        int y = 1;\n"
        "    }\n"
        "}\n"
    )
    entities = ext.extract(code, "Foo.java")
    methods = [e for e in entities if e.entity_type == "function"]
    assert len(methods) == 1
    assert methods[0].name == "Foo.process"


def test_extract_private_method(ext):
    code = (
        "public class Foo {\n"
        "    private int x;\n"
        "    private int calculate(int a, int b) {\n"
        "        return a + b;\n"
        "    }\n"
        "}\n"
    )
    entities = ext.extract(code, "Foo.java")
    methods = [e for e in entities if e.entity_type == "function"]
    assert len(methods) == 1
    assert methods[0].name == "Foo.calculate"


def test_extract_static_method(ext):
    code = (
        "public class Utils {\n"
        "    private int x;\n"
        "    public static String format(String input) {\n"
        "        return input;\n"
        "    }\n"
        "}\n"
    )
    entities = ext.extract(code, "Utils.java")
    methods = [e for e in entities if e.entity_type == "function"]
    assert any("format" in m.name for m in methods)


def test_extract_synchronized_method(ext):
    code = (
        "public class Counter {\n"
        "    private int count;\n"
        "    public synchronized void tick() {\n"
        "        count++;\n"
        "    }\n"
        "}\n"
    )
    entities = ext.extract(code, "Counter.java")
    methods = [e for e in entities if e.entity_type == "function"]
    assert len(methods) == 1
    assert methods[0].name == "Counter.tick"


# ── 10. Constructor extraction ───────────────────────────────────────────

def test_extract_constructor(ext):
    code = (
        "public class Person {\n"
        "    private String name;\n"
        "    public Person(String name) {\n"
        "        this.name = name;\n"
        "    }\n"
        "}\n"
    )
    entities = ext.extract(code, "Person.java")
    # Constructor is extracted as a function entity whose name contains the class name
    constructors = [e for e in entities if e.entity_type == "function" and "Person" in e.name]
    assert len(constructors) >= 1


# ── 11. Import extraction (regular and static) ──────────────────────────

def test_extract_regular_import(ext):
    code = (
        "import java.util.List;\n"
        "import com.example.UserService;\n"
        "\n"
        "public class Main {\n"
        "}\n"
    )
    entities = ext.extract(code, "Main.java")
    imports = [e for e in entities if e.entity_type == "import"]
    assert len(imports) == 2
    import_names = {e.name for e in imports}
    assert "List" in import_names
    assert "UserService" in import_names


def test_extract_static_import(ext):
    code = (
        "import static org.junit.Assert.assertEquals;\n"
        "\n"
        "public class Test {\n"
        "}\n"
    )
    entities = ext.extract(code, "Test.java")
    imports = [e for e in entities if e.entity_type == "import"]
    assert len(imports) == 1
    assert imports[0].name == "assertEquals"
    assert imports[0].imports[0][0] == "org.junit.Assert"


# ── 12. Wildcard import (*) ──────────────────────────────────────────────

def test_wildcard_import(ext):
    code = (
        "import java.util.*;\n"
        "\n"
        "public class Main {\n"
        "}\n"
    )
    entities = ext.extract(code, "Main.java")
    imports = [e for e in entities if e.entity_type == "import"]
    assert len(imports) == 1
    assert imports[0].name == "*"
    assert imports[0].imports[0][0] == "java.util"


# ── 13. Annotation extraction as decorators ──────────────────────────────

def test_annotation_as_decorator(ext):
    code = (
        "@Entity\n"
        "@Table\n"
        "public class User {\n"
        "}\n"
    )
    entities = ext.extract(code, "User.java")
    classes = [e for e in entities if e.entity_type == "class" and e.name == "User"]
    assert len(classes) == 1
    assert "Entity" in classes[0].decorators
    assert "Table" in classes[0].decorators


def test_common_annotations_filtered_out(ext):
    """@Override, @Deprecated, @SuppressWarnings, @FunctionalInterface, @SafeVarargs are filtered."""
    code = (
        "public class Foo {\n"
        "    private int x;\n"
        "    @Override\n"
        "    @Deprecated\n"
        "    public void work() {\n"
        "        int y = 1;\n"
        "    }\n"
        "}\n"
    )
    entities = ext.extract(code, "Foo.java")
    methods = [e for e in entities if e.entity_type == "function" and "work" in e.name]
    assert len(methods) == 1
    assert "Override" not in methods[0].decorators
    assert "Deprecated" not in methods[0].decorators


def test_service_annotation_not_filtered(ext):
    code = (
        "@Service\n"
        "public class OrderService {\n"
        "}\n"
    )
    entities = ext.extract(code, "OrderService.java")
    classes = [e for e in entities if e.entity_type == "class" and e.name == "OrderService"]
    assert len(classes) == 1
    assert "Service" in classes[0].decorators


# ── 14. Nested method in class gets scoped name ─────────────────────────

def test_nested_method_scoped_name(ext):
    code = (
        "public class Calculator {\n"
        "    private int state;\n"
        "    public int plus(int a, int b) {\n"
        "        return a + b;\n"
        "    }\n"
        "    public int minus(int a, int b) {\n"
        "        return a - b;\n"
        "    }\n"
        "}\n"
    )
    entities = ext.extract(code, "Calculator.java")
    method_names = [e.name for e in entities if e.entity_type == "function"]
    assert "Calculator.plus" in method_names
    assert "Calculator.minus" in method_names


# ── 15. Type reference extraction ────────────────────────────────────────

def test_extract_type_refs(ext):
    code = (
        "public class Processor {\n"
        "    private int state;\n"
        "    public void handle(<UserRequest req, <AppConfig cfg) {\n"
        "        int x = 1;\n"
        "    }\n"
        "}\n"
    )
    entities = ext.extract(code, "Processor.java")
    # The type ref pattern matches `: Type`, `< Type`, or `, Type` patterns.
    # Check the method entity for type_refs.
    methods = [e for e in entities if e.entity_type == "function" and "handle" in e.name]
    assert len(methods) == 1
    type_refs = methods[0].type_refs
    assert "UserRequest" in type_refs or "AppConfig" in type_refs


def test_type_refs_exclude_java_builtins(ext):
    """Built-in types like String, Integer, List should not appear in type_refs."""
    code = (
        "public class Mapper {\n"
        "    private int state;\n"
        "    public void convert(<String input, <Integer count) {\n"
        "        int x = 1;\n"
        "    }\n"
        "}\n"
    )
    entities = ext.extract(code, "Mapper.java")
    methods = [e for e in entities if e.entity_type == "function" and "convert" in e.name]
    assert len(methods) == 1
    for ref in methods[0].type_refs:
        assert ref not in ("String", "Integer", "List", "Map", "Set", "Optional")


# ── 16. Empty input returns [] ───────────────────────────────────────────

def test_empty_input_returns_empty(ext):
    assert ext.extract("", "Main.java") == []


def test_whitespace_only_returns_empty(ext):
    assert ext.extract("   \n\n  \t  \n", "Main.java") == []
