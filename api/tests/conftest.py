from tempfile import TemporaryDirectory

from pytest import MonkeyPatch


# Import the application's singleton settings without reading developer secrets
# or requiring any database / Redis server during test collection.
_configuration_dir = TemporaryDirectory(prefix="api-tests-")
with MonkeyPatch.context() as patch:
    patch.chdir(_configuration_dir.name)
    for name, value in {
        "APP_ENV": "prod",
        "APP_DEBUG": "false",
        "POSTGRES_HOST": "postgres",
        "POSTGRES_PORT": "5432",
        "POSTGRES_USERNAME": "api",
        "POSTGRES_PASSWORD": "test-only-password",
        "POSTGRES_DATABASE": "api",
        "REDIS_HOST": "redis",
        "REDIS_PORT": "6379",
        "REDIS_PASSWORD": "test-only-password",
        "PROVIDERS": "{}",
    }.items():
        patch.setenv(name, value)

    from api.core.config import settings  # noqa: F401
