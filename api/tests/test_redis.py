import os

REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
