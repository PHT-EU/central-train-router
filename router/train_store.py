from typing import List
from dataclasses import dataclass
import redis
from enum import Enum


class TrainStatus(Enum):
    """
    Enum to represent the status of a train.
    """
    INITIALIZED = "initialized"
    STARTED = "started"
    RUNNING = "running"
    STOPPED = "stopped"


@dataclass
class VaultRoute:
    harborProjects: List[str]
    periodic: bool
    repositorySuffix: str
    epochs: int = None


@dataclass
class DemoStation:
    id: int
    airflow_api_url: str
    username: str
    password: str

    def auth(self) -> tuple:
        return self.username, self.password

    def api_endpoint(self) -> str:
        return self.airflow_api_url + "/api/v1/"


class RouterRedisStore:
    def __init__(self, redis_client: redis.Redis):
        self.redis_client = redis_client

    def register_train(self, vault_route: VaultRoute):
        train_id = vault_route.repositorySuffix
        # Register participating stations and route type in redis
        self.redis_client.rpush(f"{train_id}-stations", *vault_route.harborProjects)
        self.redis_client.set(f"{train_id}-type", "periodic" if vault_route.periodic else "linear")

        # Register epochs if applicable and check that the number of epochs is set if periodic
        if vault_route.periodic and not vault_route.epochs:
            raise ValueError("Periodic train must have epochs")
        if vault_route.periodic and vault_route.epochs:
            self.redis_client.set(f"{train_id}-epochs", vault_route.epochs)

        self.redis_client.set(f"{train_id}-status", TrainStatus.INITIALIZED.value)
