import pytest
from dotenv import load_dotenv, find_dotenv
from unittest import mock


from router.router import TrainRouter


@pytest.fixture
def router():
    load_dotenv(find_dotenv())
    router = TrainRouter()

    return router


def test_router_init():
    with mock.patch.dict('os.environ', {'TRAIN_API_KEY': '12345'}):
        router = TrainRouter()

        assert router.api_key == '12345'

