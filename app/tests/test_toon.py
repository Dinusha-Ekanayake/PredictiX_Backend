from app.core.toon import to_toon, parse_toon

def test_toon_primitives():
    assert to_toon(None) == "null"
    assert to_toon(True) == "true"
    assert to_toon(False) == "false"
    assert to_toon(42) == "42"
    assert to_toon(3.14) == "3.14"
    assert to_toon("hello") == "hello"

def test_toon_special_strings():
    assert to_toon("hello, world") == '"hello, world"'
    assert to_toon("quoted \"string\"") == '"quoted \\"string\\""'
    assert to_toon("line\nbreak") == '"line\\nbreak"'
    assert to_toon("key: value") == '"key: value"'
    assert to_toon("true") == '"true"'
    assert to_toon("  with spaces  ") == '"  with spaces  "'

def test_toon_flat_dict():
    data = {
        "name": "Alice",
        "age": 30,
        "is_active": True,
        "notes": None
    }
    serialized = to_toon(data)
    parsed = parse_toon(serialized)
    assert parsed == data

def test_toon_flat_list():
    data = [1, "two", False, None]
    serialized = to_toon(data)
    parsed = parse_toon(serialized)
    assert parsed == data

def test_toon_tabular_list():
    data = [
        {"id": 1, "name": "Alice", "role": "admin"},
        {"id": 2, "name": "Bob", "role": "user"}
    ]
    serialized = to_toon(data)
    assert "[2]{id,name,role}:" in serialized
    parsed = parse_toon(serialized)
    assert parsed == data

def test_toon_nested_structures():
    data = {
        "title": "Dashboard",
        "metrics": {
            "total_users": 100,
            "active_users": 80
        },
        "tags": ["admin", "staff"],
        "users": [
            {"id": "u1", "email": "a@example.com"},
            {"id": "u2", "email": "b@example.com"}
        ]
    }
    serialized = to_toon(data)
    parsed = parse_toon(serialized)
    assert parsed == data

def test_roundtrip_complex():
    data = {
        "question": "Show me tickets",
        "history": [
            {"role": "user", "content": "hello, I need help"},
            {"role": "assistant", "content": "sure, what's wrong?"}
        ],
        "nested": {
            "key1": "value1",
            "key2": 42.5,
            "key3": True,
            "key4": None
        },
        "tickets": [
            {"id": "t1", "status": "open", "description": "Needs repair, urgency is \"high\""},
            {"id": "t2", "status": "resolved", "description": "Fixed the issue"}
        ]
    }
    serialized = to_toon(data)
    parsed = parse_toon(serialized)
    assert parsed == data

if __name__ == "__main__":
    print("Running TOON tests...")
    test_toon_primitives()
    print("test_toon_primitives passed")
    test_toon_special_strings()
    print("test_toon_special_strings passed")
    test_toon_flat_dict()
    print("test_toon_flat_dict passed")
    test_toon_flat_list()
    print("test_toon_flat_list passed")
    test_toon_tabular_list()
    print("test_toon_tabular_list passed")
    test_toon_nested_structures()
    print("test_toon_nested_structures passed")
    test_roundtrip_complex()
    print("test_roundtrip_complex passed")
    print("All tests passed successfully!")
