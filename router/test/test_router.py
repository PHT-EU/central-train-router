import os

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
    load_dotenv(find_dotenv())
    router = TrainRouter()

