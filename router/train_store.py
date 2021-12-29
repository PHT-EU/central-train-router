from typing import List
from dataclasses import dataclass
import redis


@dataclass
class VaultRoute:
    harborProjects: List[str]
    periodic: bool
    repositorySuffix: str


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

    def register_train(self, train_id: str, train_route: List[str], route_type: str = "linear"):
        pass
