SITE_CONFIG_CACHE_KEY = "site_config"
SITE_CONFIG_CACHE_TTL = 60 * 60

DEMO_HEARTBEAT_CACHE_KEY = "demo_heartbeat"

HEALTH_PING_CACHE_KEY = "health_ping"
HEALTH_PING_CACHE_TTL = 1

DEMO_CHAT_CANCEL_CACHE_TTL = 60 * 10


def demo_chat_cancel_cache_key(thread_id: str) -> str:
    """The flag a cancel request sets and a running turn checks."""
    return f"demo_chat_cancel:{thread_id}"


def demo_chat_events_channel(thread_id: str) -> str:
    """The redis pub/sub channel a thread's turn events go through."""
    return f"demo_chat_events:{thread_id}"
