from typing import List, Union
from dataclasses import dataclass
import redis
from enum import Enum
from loguru import logger


class TrainStatus(Enum):
    """
    Enum to represent the status of a train.
    """
    INITIALIZED = "initialized"
    STARTED = "started"
    RUNNING = "running"
    STOPPED = "stopped"
    COMPLETED = "completed"


class RouteTypes(Enum):
    LINEAR = "linear"
    PERIODIC = "periodic"


class UtilityStations(Enum):
    INCOMING = "pht_incoming"
    OUTGOING = "pht_outgoing"

    @classmethod
    def has_value(cls, value):
        return value in cls._value2member_map_


@dataclass
class VaultRoute:
    stations: List[str]
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

    def exists(self, train_id: str) -> bool:
        return self.redis_client.exists(f"{train_id}-stations") == 1

    def register_train(self, vault_route: VaultRoute):
        train_id = vault_route.repositorySuffix
        # Register participating stations and route type in redis
        self.redis_client.rpush(f"{train_id}-stations", *vault_route.stations)
        self.redis_client.rpush(f"{train_id}-route", *vault_route.stations)
        self.redis_client.set(f"{train_id}-type", "periodic" if vault_route.periodic else "linear")
        self.set_current_station(train_id, UtilityStations.INCOMING.value)

        # Register epochs if applicable and check that the number of epochs is set if periodic
        if vault_route.periodic and not vault_route.epochs:
            raise ValueError("Periodic train must have epochs")
        if vault_route.periodic and vault_route.epochs:
            self.redis_client.set(f"{train_id}-epochs", vault_route.epochs)
            self.redis_client.set(f"{train_id}-epoch", 0)

        self.redis_client.set(f"{train_id}-status", TrainStatus.INITIALIZED.value)

    def set_train_status(self, train_id: str, status: TrainStatus):
        self.redis_client.set(f"{train_id}-status", status.value)

    def get_train_status(self, train_id: str) -> TrainStatus:
        return TrainStatus(self.redis_client.get(f"{train_id}-status"))

    def get_route_type(self, train_id: str) -> str:
        return self.redis_client.get(f"{train_id}-type")

    def set_current_station(self, train_id: str, station_id: str):
        self.redis_client.set(f"{train_id}-current-station", station_id)

    def get_current_station(self, train_id: str) -> str:
        return self.redis_client.get(f"{train_id}-current-station")

    def get_next_station_on_route(self, train_id: str) -> str:
        next_station = self.redis_client.lpop(f"{train_id}-route")
        if next_station:
            logger.info(f"Next station on route: {next_station}")
            return next_station
        else:
            route_type = self.get_route_type(train_id)
            # linear stop at last station
            if route_type == RouteTypes.LINEAR.value:
                logger.info(f"Train {train_id} has completed its route")
                return UtilityStations.OUTGOING.value
            # for periodic train check the selected epochs
            elif route_type == RouteTypes.PERIODIC.value:
                current_round = int(self.redis_client.get(f"{train_id}-epoch"))
                logger.info(f"Train {train_id} has completed round {current_round}")
                # all rounds are finished return none
                if current_round == int(self.redis_client.get(f"{train_id}-epochs")):
                    logger.info(f"Train {train_id} has completed all rounds")
                    return UtilityStations.OUTGOING.value
                # increment epoch and re-register the route and return the next station
                else:
                    logger.info(
                        f"Train {train_id} has completed round {current_round},"
                        f" moving to round {current_round + 1}/{self.redis_client.get(f'{train_id}-epochs')}")
                    self.redis_client.set(f"{train_id}-epoch", current_round + 1)
                    self.redis_client.rpush(f"{train_id}-route",
                                            *self.redis_client.lrange(f"{train_id}-stations", 0, -1))
                    return self.redis_client.lpop(f"{train_id}-route")

    def remove_train_from_store(self, train_id: str):
        logger.info(f"Removing train {train_id} from store...")
        self.redis_client.delete(f"{train_id}-stations")
        self.redis_client.delete(f"{train_id}-route")
        self.redis_client.delete(f"{train_id}-type")
        self.redis_client.delete(f"{train_id}-epochs")
        self.redis_client.delete(f"{train_id}-epoch")
        self.redis_client.delete(f"{train_id}-status")
        logger.info("Success")
