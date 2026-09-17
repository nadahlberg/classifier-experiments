# Cursor pagination

List endpoints paginate with opaque cursors rather than page numbers, so a
client resumes exactly where it left off even while rows are inserted
ahead of it.

[`encode_cursor`](sym:8bd0be7d0497) serialises a payload dict (whatever
the selector needs to resume — typically the last row's sort key and id)
as unpadded url-safe base64 over compact JSON.
[`decode_cursor`](sym:2204ed9a5442+) re-pads and reverses it, raising
`ApplicationError("Invalid cursor")` for anything `encode_cursor` did not
mint — bad base64, bad JSON, or a non-object payload — so a tampered
cursor is a clean 400, not a server error. The token is opaque by
convention, not encryption: it carries no secrets, and the selector
re-checks ownership on every page, so forging one buys nothing.

The tests pin both directions: [a payload roundtrips
unchanged](sym:9fb3197bad4e), mixed types included, since a
`search_after` array carries floats, epoch millis and string tiebreakers;
[garbage tokens of every flavour raise `ApplicationError` rather than
crashing](sym:2c3d851136e7+); and [a token wrapping valid JSON of the wrong
shape — a bare list — fails the same way](sym:19f80ec9b977+), so no caller
needs its own `isinstance` guard.
