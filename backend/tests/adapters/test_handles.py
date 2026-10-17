"""Handle normalisation (E.164) and masking for logs."""
from app.adapters.base import mask_handle, normalize_handle


def test_normalize_phone_numbers():
    for raw in ["(415) 555-1234", "415-555-1234", "+1 415 555 1234", "14155551234"]:
        assert normalize_handle(raw) == "+14155551234"
    assert normalize_handle("+44 7911 123456") == "+447911123456"


def test_normalize_other_handles():
    assert normalize_handle(" Ansh@Example.com ") == "ansh@example.com"
    assert normalize_handle("fixture:provider_a") == "fixture:provider_a"


def test_mask():
    assert mask_handle("+14155551234") == "+1•••••1234"
    assert mask_handle("+447911123456") == "+44•••••3456"
    assert mask_handle("ansh@example.com") == "a•••@example.com"
    assert mask_handle("fixture:provider_b") == "fixture:provider_b"
    assert mask_handle(None) == "<none>"
    assert "5551234" not in mask_handle("4155551234")
