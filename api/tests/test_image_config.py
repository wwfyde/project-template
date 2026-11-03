"""Image service configuration rejects ambiguous client namespaces."""

import pytest
from pydantic import ValidationError

from api.images.config import ImageConfig

KEY = "image-client-a-primary-with-enough-entropy"
OTHER_KEY = "image-client-b-primary-with-enough-entropy"


@pytest.mark.parametrize(
    "clients",
    [
        [{"id": "same", "keys": [KEY]}, {"id": "same", "keys": [OTHER_KEY]}],
        [{"id": "a", "keys": [KEY]}, {"id": "b", "keys": [KEY]}],
        [{"id": "a", "keys": [KEY, KEY]}],
    ],
)
def test_configuration_rejects_ambiguous_external_key_namespaces(
    clients: list[dict[str, object]],
) -> None:
    with pytest.raises(ValidationError) as error:
        ImageConfig(clients=clients)
    assert KEY not in str(error.value)
