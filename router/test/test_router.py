import os

import pytest
import requests
from dotenv import load_dotenv, find_dotenv
from unittest import mock
from hvac import Client

from router import TrainRouter
from router.train_store import VaultRoute


@pytest.fixture
def router():
    load_dotenv(find_dotenv())
    router = TrainRouter()

    return router


@pytest.fixture
def vault_client():
    load_dotenv(find_dotenv())
    vault_client = Client(url=os.environ['VAULT_URL'], token=os.environ['VAULT_TOKEN'])
    return vault_client


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

    with mock.patch.dict(os.environ, {'HARBOR_PW': 'hello'}):
        # with pytest.raises(requests.exceptions.HTTPError):
        router = TrainRouter()


def test_get_route_from_vault(router, vault_client):
    # add a test route to vault
    test_id = "router-route-test"
    route = VaultRoute(repositorySuffix=test_id, harborProjects=["1", "2", "3"], periodic=False)
    print(route.__dict__)
    vault_client.secrets.kv.v2.create_or_update_secret(
        mount_point="kv-pht-routes",
        path=test_id,
        secret=route.__dict__,
    )

    router._initialize_train(train_id=test_id)

    vault_client.secrets.kv.v2.destroy_secret_versions(
        mount_point="kv-pht-routes",
        path=test_id,
        versions=[1, 2, 3]
    )
