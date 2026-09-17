"""The codebase extractor's helpers that the pattern checks lean on."""

from clx.app.selectors.codebase import _in_package


def test_a_module_sharing_a_package_prefix_is_outside_it() -> None:
    """Package membership needs a dot boundary, not a bare prefix match.

    The import and call checks attribute modules to layers with
    _in_package, and with a bare startswith a future sibling like
    clx.app.services_billing would match clx.app.services — its imports
    and calls would be judged by the wrong layer's rules, so a real
    violation could pass or a legitimate call could be flagged.
    """
    assert _in_package("clx.app.services", "clx.app.services")
    assert _in_package("clx.app.services.demo", "clx.app.services")
    assert not _in_package("clx.app.services_billing", "clx.app.services")
