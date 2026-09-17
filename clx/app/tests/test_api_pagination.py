import pytest

from clx.app.api.utils import decode_cursor, encode_cursor
from clx.app.exceptions import ApplicationError


def test_a_cursor_roundtrips_its_payload() -> None:
    """The cursor is an opaque token wrapping a JSON payload — issue #57's
    shape. What goes in must come out unchanged, including the mixed types
    a search_after array carries (scores are floats, dates arrive as epoch
    millis, tiebreakers are strings).
    """
    payload = {"sort": "newest", "after": [1755561600000, "usdc.mad_123"]}

    assert decode_cursor(encode_cursor(payload)) == payload


@pytest.mark.parametrize(
    "token",
    [
        "",
        "not-base64!!!",
        "aGVsbG8",
        encode_cursor({"sort": "newest", "after": []})[:-4] + "AAAA",
    ],
)
def test_garbage_cursors_are_rejected_not_crashed(token: str) -> None:
    """A cursor arrives from the client, so any byte sequence is possible.
    Garbage must raise ApplicationError — which ApiErrorMiddleware renders
    as the standard {"message", "extra"} 400 — rather than letting a
    binascii or JSON error bubble into a 500.
    """
    with pytest.raises(ApplicationError):
        decode_cursor(token)


def test_a_cursor_wrapping_a_non_object_is_rejected() -> None:
    """decode_cursor promises a dict payload to its callers; a token that
    decodes to valid JSON of the wrong shape — here "WzEsMl0", the
    encoding of the bare list [1,2] — must fail the same way as garbage,
    or every caller would need its own isinstance guard before reading
    keys.
    """
    with pytest.raises(ApplicationError):
        decode_cursor("WzEsMl0")
