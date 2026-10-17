import pytest

from app.context.domain import load_pack


def test_pack_loads_and_is_versioned():
    pack = load_pack()
    assert (pack.name, pack.version) == ("home_repair", "v1")
    assert len(pack.examples) >= 8
    assert len(pack.verification_predicates) == 9
    assert "visit_charge_cents" in pack.approval_boundaries["material_fields"]
    assert load_pack() is pack


def test_pack_rejects_path_traversal():
    with pytest.raises(ValueError):
        load_pack("../core")
