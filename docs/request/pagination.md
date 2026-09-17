# Cursor pagination

List endpoints paginate with opaque cursors rather than page numbers, so a
client resumes exactly where it left off even while rows are inserted
ahead of it.

[`encode_cursor`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/pagination.py#L9-L12) serialises a payload dict (whatever
the selector needs to resume — typically the last row's sort key and id)
as unpadded url-safe base64 over compact JSON.
[`decode_cursor`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/pagination.py#L15-L24) re-pads and reverses it, raising
`ApplicationError("Invalid cursor")` for anything `encode_cursor` did not
mint — bad base64, bad JSON, or a non-object payload — so a tampered
cursor is a clean 400, not a server error. The token is opaque by
convention, not encryption: it carries no secrets, and the selector
re-checks ownership on every page, so forging one buys nothing.

The tests pin both directions: [a payload roundtrips
unchanged](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_pagination.py#L7-L15), mixed types included, since a
`search_after` array carries floats, epoch millis and string tiebreakers;
[garbage tokens of every flavour raise `ApplicationError` rather than
crashing](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_pagination.py#L27-L34); and [a token wrapping valid JSON of the wrong
shape — a bare list — fails the same way](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_pagination.py#L37-L45), so no caller
needs its own `isinstance` guard.
