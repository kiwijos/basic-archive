from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    meili_url: str
    # A search-only key: it cannot write, change settings or read documents by id.
    meili_key: str

    default_page_size: int = 20
    max_page_size: int = 50
    http_port: int = 8000

    # Identical queries are answered from memory for this long, so a correction shows up within seconds.
    cache_ttl_seconds: float = 5.0
    cache_max_entries: int = 1000
    # The cache also has a size budget, so many long answers cannot exhaust the pod.
    cache_max_bytes: int = 32 * 1024 * 1024

    # Per client address and per pod; with several replicas the limit is per replica.
    rate_limit_per_minute: int = 120
    rate_limit_window_seconds: float = 60.0
    # How many client addresses are tracked at once; beyond this the longest-unseen one is forgotten.
    rate_limit_max_clients: int = 10_000
    # Proxies in front of the service (Traefik is one): the client is the address this many entries
    # from the end of X-Forwarded-For, which is what the nearest proxy added and a client cannot forge.
    trusted_proxies: int = 1

    # Where Cantaloupe serves images; the identifier is the Image id.
    iiif_base_url: str = "/iiif/3"
