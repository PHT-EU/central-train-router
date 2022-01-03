import os

import pytest
import requests
from dotenv import load_dotenv, find_dotenv
from unittest import mock
from hvac import Client
import redis

from router import TrainRouter
from router.events import RouterErrorCodes
from router.train_store import VaultRoute
import pika

CHANNEL = "router-test-channel"
EXCHANGE = "pht"
ROUTING_KEY = "tr"


def publish_test_message(message):
    ampg_url = os.getenv("AMPQ_URL")
    connection = pika.BlockingConnection(pika.URLParameters(ampg_url))
    channel = connection.channel()
    channel.exchange_declare(exchange=EXCHANGE, exchange_type='topic')
    channel.basic_publish(exchange=EXCHANGE, routing_key=ROUTING_KEY, body=message)
    print(" [x] Sent %r" % message)


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


@pytest.fixture
def redis_client():
    load_dotenv(find_dotenv())
    return redis.Redis(host=os.environ['REDIS_HOST'], decode_responses=True)


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


def test_initialize_train(router, vault_client, redis_client):
    # add a test route to vault
    test_id = "router-test"
    route = VaultRoute(repositorySuffix=test_id, harborProjects=["1", "2", "3"], periodic=False)
    vault_client.secrets.kv.v2.create_or_update_secret(
        mount_point="kv-pht-routes",
        path=test_id,
        secret=route.__dict__,
    )
    redis_client.delete(f"{test_id}-stations")
    router._initialize_train(train_id=test_id)
    assert redis_client.lrange(f"{test_id}-stations", 0, -1) == ["1", "2", "3"]
    assert redis_client.get(f"{test_id}-type") == "linear"
    assert redis_client.get(f"{test_id}-status") == "initialized"

    # cleanup created test values
    redis_client.delete(f"{test_id}-stations")
    redis_client.delete(f"{test_id}-type")
    redis_client.delete(f"{test_id}-status")
    vault_client.secrets.kv.v2.destroy_secret_versions(
        mount_point="kv-pht-routes",
        path=test_id,
        versions=[1, 2, 3]
    )


def test_router_start_train(router, vault_client, redis_client):
    test_id = "router-test"

    # initialize train route in redis and vault
    route = VaultRoute(repositorySuffix=test_id, harborProjects=["1", "2", "3"], periodic=False)
    vault_client.secrets.kv.v2.create_or_update_secret(
        mount_point="kv-pht-routes",
        path=test_id,
        secret=route.__dict__,
    )
    redis_client.delete(f"{test_id}-stations")
    router._initialize_train(train_id=test_id)

    # setup test train in pht incoming repo
    test_base_image = "test/test-image"
    harbor_url = os.getenv("HARBOR_API")
    params = {
        "from": test_base_image + ":latest",
    }
    url = f"{harbor_url}/projects/pht_incoming/repositories/{test_id}/artifacts"
    response = requests.post(url=url, params=params, auth=router.harbor_auth, headers=router.harbor_headers)
    print(response.text)

    # unregistered train should fail
    response = router._start_train(train_id="fails")
    assert response.error_code == RouterErrorCodes.TRAIN_NOT_FOUND

    print(redis_client.get(f"{test_id}-status"))
    # registered train should succeed
    router._start_train(train_id=test_id)