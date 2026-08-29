from slowapi import Limiter
from slowapi.util import get_remote_address

# Keyed by client IP. In-memory storage by default — fine for a single-
# process learning project; swap in a Redis storage backend if this ever
# runs with multiple workers.
limiter = Limiter(key_func=get_remote_address)
