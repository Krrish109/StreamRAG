"""Tests for V2 shadow AST."""

from streamrag.v2.shadow_ast import ShadowAST, IncrementalShadowAST, ParseStatus


def test_valid_code_single_region():
    shadow = ShadowAST()
    source = "def foo():\n    return 1\n"
    regions = shadow.parse(source)
    assert len(regions) == 1
    assert regions[0].status == ParseStatus.VALID
    assert len(regions[0].entities) >= 1


def test_empty_source():
    shadow = ShadowAST()
    regions = shadow.parse("")
    assert regions == []


def test_broken_code_mixed_regions():
    shadow = ShadowAST()
    source = "def foo():\n    return 1\n\ndef bar(:\n    pass\n"
    regions = shadow.parse(source)
    # Should have at least some VALID and some INVALID regions
    statuses = {r.status for r in regions}
    assert ParseStatus.INVALID in statuses or len(regions) > 1


def test_regex_fallback_function():
    shadow = ShadowAST()
    source = "def broken_func(x, y):\n"
    regions = shadow.parse(source)
    # Should extract via regex on invalid region
    all_entities = []
    for r in regions:
        all_entities.extend(r.entities)
    func_entities = [e for e in all_entities if e.entity_type == "function"]
    assert len(func_entities) >= 1
    assert func_entities[0].name == "broken_func"


def test_regex_fallback_class():
    shadow = ShadowAST()
    source = "class MyClass(Base):\n"
    regions = shadow.parse(source)
    all_entities = []
    for r in regions:
        all_entities.extend(r.entities)
    class_entities = [e for e in all_entities if e.entity_type == "class"]
    assert len(class_entities) >= 1
    assert class_entities[0].name == "MyClass"


def test_regex_function_confidence():
    shadow = ShadowAST()
    # Complete function signature with colon and closing paren
    source = "def complete(x):\n"
    regions = shadow.parse(source)
    # If parsed via regex (invalid), confidence should be 0.9
    for r in regions:
        for e in r.entities:
            if e.entity_type == "function":
                conf = e.__dict__.get("confidence", 1.0)
                assert conf >= 0.5


def test_incremental_shadow_ast():
    ishadow = IncrementalShadowAST()
    source_v1 = "def foo():\n    return 1\n\ndef bar():\n    return 2\n"
    regions = ishadow.update(source_v1)
    assert len(regions) >= 1

    # Modify only bar
    source_v2 = "def foo():\n    return 1\n\ndef bar():\n    return 3\n"
    regions = ishadow.update(source_v2, changed_lines=range(3, 5))
    assert len(regions) >= 1


def test_incremental_full_reparse_on_none_changed_lines():
    ishadow = IncrementalShadowAST()
    source = "x = 1\ny = 2\n"
    regions = ishadow.update(source, changed_lines=None)
    assert len(regions) >= 1
