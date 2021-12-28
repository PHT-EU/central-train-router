import os

import pytest
from dotenv import load_dotenv, find_dotenv
from unittest import mock


from router.train_router import TrainRouter


@pytest.fixture
def router():
    load_dotenv(find_dotenv())
    router = TrainRouter()

    return router


def test_router_init():
    load_dotenv(find_dotenv())
    router = TrainRouter()

    with mock.patch.dict(os.environ, {'VAULT_URL': ''}):
        with pytest.raises(ValueError):
            router = TrainRouter()

    with mock.patch.dict(os.environ, {'VAULT_TOKEN': ''}):
        with pytest.raises(ValueError):
            router = TrainRouter()

    with mock.patch.dict(os.environ, {'HARBOR_API': ''}):
        with pytest.raises(ValueError):
            router = TrainRouter()

    with mock.patch.dict(os.environ, {'HARBOR_USER': ''}):
        with pytest.raises(ValueError):
            router = TrainRouter()

    with mock.patch.dict(os.environ, {'HARBOR_PW': ''}):
        with pytest.raises(ValueError):
            router = TrainRouter()
    with mock.patch.dict(os.environ, {'REDIS_HOST': ''}):
        with pytest.raises(ValueError):
            router = TrainRouter()

