def default_lb_name(uid: str) -> str:
    """Name the DO cloud controller gives a Service's load balancer."""
    return f"a{uid.replace('-', '')}"[:32]
