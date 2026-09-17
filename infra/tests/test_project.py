"""Guard the get-or-create semantics of the DigitalOcean project.

DigitalOcean project names are unique per account, and `__main__.py`
used to declare `do.Project(...)` unconditionally -- a plain create.
A derived project's very first deploy failed on exactly that: the
account already had a project with the configured name, so the create
409'd and the whole initial `pulumi up` died (2026-08-21).

`project_args` is the fix: look the name up first, and when a project
already exists, hand back its id so `__main__.py` declares the resource
with `import_=` -- Pulumi adopts the existing project into the stack
instead of colliding with it. The two branches converge: after a fresh
create, the next deploy's lookup finds the project the stack itself
made, and Pulumi ignores `import_` for a resource already in its state.

The subtle half of adoption is that an import fails when the program's
declared inputs differ from the live resource. An existing project
carries a purpose, maybe a description -- so the adopt branch must
mirror the looked-up values into the inputs, and empty strings must
become None so unset optionals don't register as a diff either.

The lookup is injected (`__main__.py` passes `do.get_project`) because
the root test env deliberately carries pulumi core but no provider
SDKs -- a module-level `import pulumi_digitalocean` here would break
collection for the whole suite.
"""

from types import SimpleNamespace

from infra.project import project_args

EXISTING = SimpleNamespace(
    id="prj-123",
    description="Legal analytics",
    purpose="Web Application",
    environment="Production",
    is_default=False,
)


def find_existing(name):
    """A lookup that finds EXISTING, whatever the name."""
    return EXISTING


def find_nothing(name):
    """A lookup with no project by that name. The invoke raises rather
    than returning empty, so not-found arrives as an exception. A bad
    token lands here too, which is fine: the create branch then fails
    loudly with the provider's own auth error."""
    raise Exception(f"no projects found with name {name}")


def test_a_missing_project_is_created_plain():
    """The fresh-account case: no import id, inputs are just the name."""
    inputs, import_id = project_args("my-app", find_nothing)

    assert import_id is None
    assert inputs == {"name": "my-app"}


def test_an_existing_project_is_adopted_not_recreated():
    """The incident case: the id comes back so the resource is declared
    with `import_=`, turning the 409 into an adoption."""
    inputs, import_id = project_args("my-app", find_existing)

    assert import_id == "prj-123"


def test_adopted_inputs_mirror_the_live_project():
    """An import is rejected on any input diff, so every optional the
    live project carries must be declared with the live value."""
    inputs, _ = project_args("my-app", find_existing)

    assert inputs == {
        "name": "my-app",
        "description": "Legal analytics",
        "purpose": "Web Application",
        "environment": "Production",
        "is_default": False,
    }


def test_empty_live_strings_become_unset():
    """DO returns "" for optionals a project never set. Declaring ""
    where the provider holds null is an input diff, and an input diff
    fails the import -- so empties must map to None."""
    found = SimpleNamespace(
        id="prj-456",
        description="",
        purpose="",
        environment="",
        is_default=True,
    )

    inputs, import_id = project_args("my-app", lambda name: found)

    assert import_id == "prj-456"
    assert inputs == {
        "name": "my-app",
        "description": None,
        "purpose": None,
        "environment": None,
        "is_default": True,
    }
