"""Guard the derived load balancer name the AAAA record depends on.

The DigitalOcean cloud controller manager names a Service's load
balancer with Kubernetes' `cloudprovider.DefaultLoadBalancerName`:
"a" plus the Service UID, dashes stripped, truncated to 32 characters.
The DO API never hands that name back through the Service, so
`__main__.py` re-derives it to find the LB with
`get_load_balancer_output` and read its `ipv6` for the apex AAAA
record.

That record is why this matters: an AAAA record Pulumi does not manage
survives a cluster/LB replacement pointing at the deleted LB's IPv6,
and IPv6-capable clients then fail intermittently while IPv4 users see
a healthy site (user-facing incident, 2026-08-19). Managing it requires
the lookup, and the lookup requires this derivation.

If the derivation drifts from the CCM's, `get_load_balancer_output`
finds nothing and `pulumi up` fails loudly at deploy time -- after
merge, in CI. This test catches the drift before that.
"""

from infra.load_balancer import default_lb_name


def test_default_lb_name_matches_kubernetes_derivation():
    """A real-shaped UID: prefix "a", strip dashes, cap at 32 chars.

    The cap is the subtle part -- a 36-char UID strips to 32, and the
    "a" prefix makes 33, so the UID's last character falls off. Without
    the cap the derived name is one character too long and every lookup
    misses.
    """
    assert (
        default_lb_name("2ad2cf82-a10b-4a72-a380-6df913e5f375")
        == "a2ad2cf82a10b4a72a3806df913e5f37"
    )
