from pathlib import Path

import pytest
from django.test import Client

from clx.app.services.user import user_create

COTTON = Path(__file__).parent.parent / "templates" / "cotton"
ICONS = Path(__file__).parent.parent / "static" / "icons"

CHROME = {"nav", "footer", "messages"}


@pytest.mark.django_db
def test_every_root_cotton_primitive_is_documented_on_the_components_page(
    client: Client,
) -> None:
    """Components at the root of cotton/ are the design-system primitives,
    and /demos/components/ is their documentation.

    Cotton only compiles a component when a page actually renders it, so a
    primitive that never appears here could ship broken and fail on whichever
    page reaches for it first. Rendering the library page exercises every
    primitive, and checking for each one's section anchor means adding a new
    root-level component without documenting it fails this test.

    CHROME lists the root-level components that are app furniture (nav,
    footer, ...) rather than primitives — they live at the root because every
    layout uses them, not because they are part of the design system.
    """
    primitives = {path.stem for path in COTTON.glob("*.html")} - CHROME

    client.force_login(user_create(email="primitives@example.com"))
    response = client.get("/demos/components/", secure=True)
    html = response.content.decode()

    assert response.status_code == 200
    assert primitives
    for name in sorted(primitives):
        assert f'id="{name}"' in html, (
            f"{name} has no section on /demos/components/"
        )


@pytest.mark.django_db
def test_every_brand_asset_is_documented_on_the_components_page(
    client: Client,
) -> None:
    """static/icons/ holds the brand image assets — favicon, home-screen
    icons, PWA icons — and the Logos section on /demos/components/ is where
    a rebrand goes to see them all at once.

    Referencing each file by name on the page is what keeps that section
    honest: adding a new brand asset without documenting where it is wired
    in fails here, the same forcing function the primitives get.
    """
    assets = {path.name for path in ICONS.iterdir() if path.is_file()}

    client.force_login(user_create(email="assets@example.com"))
    response = client.get("/demos/components/", secure=True)
    html = response.content.decode()

    assert response.status_code == 200
    assert assets
    for name in sorted(assets):
        assert name in html, f"{name} is not shown on /demos/components/ logos"
