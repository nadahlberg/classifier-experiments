"""Guard the get-or-create semantics of the DO container registry.

DigitalOcean allows exactly one container registry per account, and
`__main__.py` used to declare `do.ContainerRegistries(...)`
unconditionally -- so on an account that already has a registry, a
derived project's first deploy fails on the create, the same failure
class test_project.py describes for the DO project (2026-08-21).

`registry_args` applies the same fix: look the name up first, and when
the registry exists, hand back its id so the resource is declared with
`import_=` and Pulumi adopts it instead of colliding. The branches
converge the same way -- after a fresh create the lookup finds the
stack's own registry, and `import_` is ignored for a resource already
in state.

Two inputs are deliberately treated differently on adoption:

- `subscription_tier_slug` keeps the env value, not the live one.
  Mirroring live would pin the tier forever (the converged path runs
  the adopt branch on every deploy, so a changed
  DIGITALOCEAN_REGISTRY_TIER would never apply). The cost is that a
  true adoption whose live tier differs from the env fails the import
  with a visible diff -- the fix is aligning the secret, which is the
  honest resolution.
- `region` mirrors live, because a registry cannot move regions: the
  live value is the only importable one, and on the converged path the
  live region is whatever the stack created, so nothing drifts.

If the account's registry has a *different name* than the configured
one, adoption is impossible (the lookup misses, the create still
collides at the account level) and the deploy fails with DO's own
error; the fix is setting DIGITALOCEAN_REGISTRY_NAME to the existing
registry's name.

The lookup is injected (`__main__.py` passes
`do.get_container_registry`) for the same reason as in project.py: the
root test env carries pulumi core but no provider SDKs.
"""

from types import SimpleNamespace

from infra.registry import registry_args

EXISTING = SimpleNamespace(
    id="my-registry",
    name="my-registry",
    region="sfo2",
    subscription_tier_slug="professional",
)


def find_existing(name):
    """A lookup that finds EXISTING, whatever the name."""
    return EXISTING


def find_nothing(name):
    """A lookup with no registry by that name; not-found arrives as an
    exception, and a bad token lands here too -- the create branch then
    fails loudly with the provider's own error."""
    raise Exception(f"registry {name} not found")


def test_a_missing_registry_is_created_from_the_env():
    """The fresh-account case: no import id, inputs straight from config."""
    inputs, import_id = registry_args(
        "my-registry", "basic", "nyc3", find_nothing
    )

    assert import_id is None
    assert inputs == {
        "name": "my-registry",
        "subscription_tier_slug": "basic",
        "region": "nyc3",
    }


def test_an_existing_registry_is_adopted_not_recreated():
    """The incident case: the id comes back so the resource is declared
    with `import_=`, turning the account-level collision into adoption."""
    inputs, import_id = registry_args(
        "my-registry", "professional", "nyc3", find_existing
    )

    assert import_id == "my-registry"


def test_adoption_keeps_the_env_tier_and_the_live_region():
    """The asymmetry this module exists to record: tier stays env-driven
    so later tier changes still deploy (the converged path runs this
    branch every time), while region mirrors live because a registry
    cannot move and any other value would fail the import."""
    inputs, _ = registry_args(
        "my-registry", "professional", "nyc3", find_existing
    )

    assert inputs == {
        "name": "my-registry",
        "subscription_tier_slug": "professional",
        "region": "sfo2",
    }


def test_an_empty_live_region_becomes_unset():
    """Registries created before regions existed return "" -- declaring
    the config region against a null live value is an input diff, and an
    input diff fails the import, so empty maps to None."""
    found = SimpleNamespace(
        id="old-registry",
        name="old-registry",
        region="",
        subscription_tier_slug="clx",
    )

    inputs, import_id = registry_args(
        "old-registry", "clx", "nyc3", lambda name: found
    )

    assert import_id == "old-registry"
    assert inputs["region"] is None
