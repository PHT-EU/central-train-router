import os
from pprint import pprint

import docker
import redis
import requests
from typing import List
import random
import logging
import hvac
from hvac.exceptions import InvalidPath
from requests import HTTPError
from loguru import logger

from router.messages import RouterCommand, RouterResponse
from router.events import RouterEvents, RouterResponseEvents, RouterErrorCodes
from router.train_store import RouterRedisStore, VaultRoute, DemoStation, TrainStatus, UtilityStations

LOGGER = logging.getLogger(__name__)


class TrainRouter:
    vault_url: str
    vault_token: str
    vault_client: hvac.Client
    vault_headers: dict
    vault_route_engine: str = "routes"
    harbor_api_url: str
    harbor_user: str
    harbor_password: str
    harbor_headers: dict
    harbor_auth: tuple
    redis_host: str
    redis: redis.Redis
    redis_store: RouterRedisStore
    auto_start: bool = False
    demo_mode: bool = False
    demo_stations: dict = None
    docker_client: docker.DockerClient
    interop_registry: str
    interop_registry_username: str
    interop_registry_password: str

    def __init__(self):
        # setup connections to external services
        self.setup()
        # sync redis with vault
        self.sync_routes_with_vault()

    def setup(self):
        """
        Set up the connections to external services
        """
        logger.info("Setting up vault connection, with environment variables")
        self.vault_url = os.getenv("VAULT_URL")
        if not self.vault_url:
            raise ValueError("VAULT_URL not set in environment variables")
        self.vault_token = os.getenv("VAULT_TOKEN")
        if not self.vault_token:
            raise ValueError("VAULT_TOKEN not set in environment variables")
        # remove trailing slash from vault url if present
        if self.vault_url[-1] == "/":
            self.vault_url = self.vault_url[:-1]
        logger.info("Connecting to Vault - URL: {}", self.vault_url)
        self.vault_headers = {"X-Vault-Token": self.vault_token}
        self.vault_client = hvac.Client(url=self.vault_url, token=self.vault_token)
        logger.info("Successfully connected to Vault")

        logger.info("Setting up harbor connection, with environment variables")
        self.harbor_api_url = os.getenv("HARBOR_URL") + "/api/v2.0"
        if not self.harbor_api_url:
            raise ValueError("HARBOR_URL not set in environment variables")
        self.harbor_user = os.getenv("HARBOR_USER")
        if not self.harbor_user:
            raise ValueError("HARBOR_USER not set in environment variables")
        self.harbor_password = os.getenv("HARBOR_PW")
        if not self.harbor_password:
            raise ValueError("HARBOR_PW not set in environment variables")
        logger.info("Connecting to Harbor - URL: {}", self.harbor_api_url)
        self.harbor_headers = {'accept': 'application/json', 'Content-Type': 'application/json'}
        self.harbor_auth = (self.harbor_user, self.harbor_password)
        try:
            url = f"{self.harbor_api_url}/projects"
            r = requests.get(url, headers=self.harbor_headers, auth=self.harbor_auth)
            print(r.json())
            r.raise_for_status()
        except HTTPError as e:
            logger.error("Harbor connection failed with error: {}", e)
            raise e
        logger.info("Successfully connected to Harbor")

        logger.info("Setting up redis connection, with environment variables")
        self.redis_host = os.getenv("REDIS_HOST")
        if not self.redis_host:
            raise ValueError("REDIS_HOST not set in environment variables")
        self.redis = redis.Redis(host=self.redis_host, decode_responses=True)
        self.redis_store = RouterRedisStore(self.redis)
        logger.info("Successfully connected to Redis")

        self._setup_docker_registries()

        # class variables for running train router in demonstration mode
        self.auto_start = os.getenv("AUTO_START") == "true"
        self.demo_mode = os.getenv("DEMONSTRATION_MODE") == "true"
        if self.demo_mode:
            self.demo_stations = {}
            logger.info("Demonstration mode detected, attempting to load demo stations")
            self._get_demo_stations()

    def _setup_docker_registries(self):
        logger.info("Setting up docker client from environment")
        self.docker_client = docker.from_env()
        logger.info("Successfully connected to Docker")

        logger.info("Loging into registries...")
        logger.info("Logging into Tue Harbor...")
        login_result = self.docker_client.login(username=self.harbor_user,
                                                password=self.harbor_password,
                                                registry=os.getenv("HARBOR_URL"))

        if login_result['Status'] != 'Login Succeeded':
            logger.error(f"Failed to login to Tue Harbor \n {login_result}")

        logger.info(f"Log in result Tue: {login_result['Status']}")
        logger.info("Logging into interop registry...")

        self.interop_registry = os.getenv("INTEROP_REGISTRY_URL")
        self.interop_registry_username = os.getenv("INTEROP_REGISTRY_USER")
        self.interop_registry_password = os.getenv("INTEROP_REGISTRY_PASSWORD")

        login_result = self.docker_client.login(username=self.interop_registry_username,
                                                password=self.interop_registry_password,
                                                registry=self.interop_registry)

        if login_result['Status'] != 'Login Succeeded':
            logger.error(f"Failed to login to Interop registry \n {login_result}")

        logger.info(f"Log in result interop: {login_result['Status']}")

    def process_command(self, command: RouterCommand) -> RouterResponse:
        """
        Main processing method of the train router. This method will process a command from the message queue and
        return a response to be published to the message queue.
        :param command:
        :return:
        """

        if command.event_type == RouterEvents.TRAIN_BUILT:
            response = self._initialize_train(command.train_id)

        elif command.event_type == RouterEvents.TRAIN_START:
            response = self._start_train(command.train_id)

        elif command.event_type == RouterEvents.TRAIN_STOP:
            response = self._stop_train(command.train_id)

        elif command.event_type == RouterEvents.TRAIN_PUSHED:
            # ignore system push events
            if command.operator == "system":
                logger.info(f"Train - {command.train_id} - Ignoring system push event")
                response = RouterResponse(RouterResponseEvents.IGNORED, train_id=command.train_id,
                                          message="Ignored system event")
            else:
                response = self._route_train(command.train_id)

        elif command.event_type == RouterEvents.TRAIN_STATUS:
            response = self._read_train_status(command.train_id)

        elif command.event_type == RouterEvents.TRAIN_RESET:
            response = self._reset_train(command.train_id)

        else:
            logger.error("Unrecognized event type: {}", command.event_type)
            response = RouterResponse(RouterResponseEvents.FAILED, train_id=command.train_id,
                                      message="Unrecognized event type")

        return response

    def _initialize_train(self, train_id: str) -> RouterResponse:
        """
        Get route from vault and initialize train in redis
        :param train_id:
        :return:
        """
        logger.info("Initializing train {}", train_id)
        logger.info("Getting route from vault...")
        try:
            vault_data = self.vault_client.secrets.kv.v1.read_secret(
                path=train_id,
                mount_point=self.vault_route_engine
            )
            logger.info("Success")
        except Exception as e:
            logger.error("Failed to get route from vault: {}", e)
            return RouterResponse(
                event=RouterResponseEvents.FAILED,
                train_id=train_id,
                message="Failed to get route from vault"
            )

        route = VaultRoute(**vault_data["data"])
        logger.info("Initializing train in redis...")
        self.redis_store.register_train(route)
        logger.info("Success")
        return RouterResponse(
            event=RouterResponseEvents.BUILT,
            train_id=train_id,
            message="Successfully initialized train"
        )

    def _start_train(self, train_id: str) -> RouterResponse:
        """
        Check the status of a train, if it is not running, attempt to start it

        :param train_id:
        :return: Response object to be sent to the queue
        """
        logger.info("Attempting to start train - {}", train_id)
        try:
            train_status = self.redis_store.get_train_status(train_id)
        # if the train is not found return an error response
        except ValueError:
            logger.error("Train {} does not exist in redis", train_id)

            logger.info("Attempting to recover route from vault...")
            try:
                # attempt to recover the route from vault by reinitializing the train
                response = self._initialize_train(train_id)
                if response.event == RouterResponseEvents.FAILED:
                    logger.error("Failed to recover route from vault")
                    return RouterResponse(
                        event=RouterResponseEvents.FAILED,
                        train_id=train_id,
                        error_code=RouterErrorCodes.TRAIN_NOT_FOUND,
                        message="Failed to recover route from vault"
                    )
                train_status = self.redis_store.get_train_status(train_id)
                logger.info("Success")
            except Exception as e:
                logger.error("Failed to get route from vault: {}", e)

                return RouterResponse(
                    event=RouterResponseEvents.FAILED,
                    train_id=train_id,
                    error_code=RouterErrorCodes.TRAIN_NOT_FOUND)
        # if train is already running return error response
        if train_status == TrainStatus.STARTED or train_status == TrainStatus.RUNNING:
            logger.error("Train {} is already started.", train_id)
            return RouterResponse(
                event=RouterResponseEvents.FAILED,
                train_id=train_id,
                message="Train is already started",
                error_code=RouterErrorCodes.TRAIN_ALREADY_STARTED
            )

        if train_status == TrainStatus.STOPPED:
            logger.info("Train is stopped, restarting...")
            origin_station = self.redis_store.get_current_station(train_id)
            destination_station = self.redis_store.get_next_station_on_route(train_id)

        elif train_status == TrainStatus.INITIALIZED:
            logger.info("Moving train out of pht_incoming...")
            origin_station = self.redis_store.get_current_station(train_id)
            destination_station = self.redis_store.get_next_station_on_route(train_id)

        else:
            logger.error("Unknown train status: {}", train_status)
            return RouterResponse(
                event=RouterResponseEvents.FAILED,
                train_id=train_id,
                error_code=RouterErrorCodes.TRAIN_NOT_FOUND
            )

        # Move the train images
        self._move_train(train_id=train_id, origin=origin_station, dest=destination_station)
        self.redis_store.set_train_status(train_id, TrainStatus.RUNNING)
        self.redis_store.set_current_station(train_id, destination_station)
        logger.info("Train {} successfully started", train_id)
        return RouterResponse(
            event=RouterResponseEvents.STARTED,
            train_id=train_id,
            message="Train started successfully"
        )

    def _stop_train(self, train_id: str) -> RouterResponse:
        """
        Check the status of a train, if it is running, attempt to stop it

        :param train_id:
        :return: Response object to be sent to the queue
        """
        logger.info("Attempting to stop train - {}", train_id)
        if not self.redis_store.exists(train_id):
            logger.error("Train {} does not exist in redis", train_id)
            return RouterResponse(
                event=RouterResponseEvents.FAILED,
                train_id=train_id,
                error_code=RouterErrorCodes.TRAIN_NOT_FOUND)

        train_status = self.redis_store.get_train_status(train_id)
        # if train is already stopped return error response
        if train_status == TrainStatus.STOPPED:
            logger.error("Train {} is already stopped.", train_id)
            return RouterResponse(
                event=RouterResponseEvents.FAILED,
                train_id=train_id,
                message="Train is already stopped",
                error_code=RouterErrorCodes.TRAIN_ALREADY_STOPPED
            )

        # if train is not running return error response
        if train_status == TrainStatus.INITIALIZED:
            logger.error("Train {} is not running.", train_id)
            return RouterResponse(
                event=RouterResponseEvents.FAILED,
                train_id=train_id,
                message="Train is not running",
                error_code=RouterErrorCodes.TRAIN_NOT_STARTED
            )

        # if train is not running return error response
        if train_status == TrainStatus.RUNNING or train_status == TrainStatus.STARTED:
            logger.info("Train is running, stopping...")
            self.redis_store.set_train_status(train_id, TrainStatus.STOPPED)
            logger.info("Train {} successfully stopped", train_id)
            return RouterResponse(
                event=RouterResponseEvents.STOPPED,
                train_id=train_id,
                message="Train stopped successfully"
            )

        else:
            logger.error("Unknown train status: {} for train: ", train_status, train_id)

    def _read_train_status(self, train_id: str) -> RouterResponse:
        status = self.redis_store.get_train_status(train_id)
        return RouterResponse(
            event=RouterResponseEvents.STATUS,
            train_id=train_id,
            message=status.value
        )

    def _route_train(self, train_id: str) -> RouterResponse:
        """
        Processes push events from the registry to route a running train between stations

        :param train_id:
        :return:
        """
        current_station = self.redis_store.get_current_station(train_id)
        next_station = self.redis_store.get_next_station_on_route(train_id)

        status = self.redis_store.get_train_status(train_id)
        if status == TrainStatus.INITIALIZED or status == TrainStatus.STOPPED or status == TrainStatus.COMPLETED:
            return RouterResponse(
                event=RouterResponseEvents.FAILED,
                train_id=train_id,
                message="Train is not running",
                error_code=RouterErrorCodes.TRAIN_NOT_RUNNING
            )

        # move finished train to outgoing repository
        if next_station == UtilityStations.OUTGOING.value:
            logger.info("Train {} finished it's route -> moving to pht_outgoing", train_id)
            self._move_train(train_id=train_id, origin=current_station, dest=next_station)
            self.redis_store.set_train_status(train_id, TrainStatus.COMPLETED)
            logger.info(f"Removing train {train_id} from vault storage...")
            self._remove_route_from_vault(train_id)
            logger.info(f"Train {train_id} successfully removed from vault storage")
            return RouterResponse(
                event=RouterResponseEvents.COMPLETED,
                train_id=train_id,
                message="Train completed successfully"
            )

        # move train to next station
        logger.info("Train {} moving from station {} to next station {}", train_id, current_station, next_station)
        try:
            self._move_train(train_id=train_id, origin=current_station, dest=next_station)

        except Exception as e:
            logger.error("Error moving train {} from {} to {}: {}", train_id, current_station, next_station, e)
            return RouterResponse(
                event=RouterResponseEvents.FAILED,
                train_id=train_id,
                message=f"Error moving train - Origin: {current_station} - Destination: {next_station}"
            )
        return RouterResponse(
            event=RouterResponseEvents.MOVED,
            train_id=train_id,
            message=f"Origin: {current_station} - Destination: {next_station}"
        )

    def sync_routes_with_vault(self):
        """
        Gets all routes stored in vault and compares them with the ones stored in redis, if a route does not exist in
        redis it will be added.

        :return:
        """

        logger.info("Syncing redis with vault storage...")
        routes = self._get_all_routes_from_vault()

        if routes:
            for route in routes:
                if not self.redis_store.exists(route.repositorySuffix):
                    logger.info("Route for train {} does not exist in redis, adding...", route.repositorySuffix)
                    self.redis_store.register_train(route)
                else:
                    logger.info("Route for train {} already exists in redis, skipping...", route.repositorySuffix)
        else:
            logger.info("No routes found in vault storage")

    def _get_all_routes_from_vault(self) -> List[VaultRoute]:
        """
        Queries the kv-pht-routes secret engines and returns a list of the keys (train ids) stored in vault
        :return:
        """

        try:
            vault_secrets = self.vault_client.secrets.kv.v1.list_secrets(path="", mount_point="routes")
        except Exception as e:
            logger.error("Error while getting routes from vault: {}", e)
            return []
        secret_keys = vault_secrets.get("data").get("keys")
        pprint(secret_keys)
        if not secret_keys:
            return []
        vault_routes = []
        for key in secret_keys:
            logger.info(f"Found route for train {key} in vault")
            try:
                route = self.vault_client.secrets.kv.v1.read_secret(path=key, mount_point="routes")
            except InvalidPath as e:
                logger.error(f"No route data for train {key} found in vault")
                logger.error(e)
                continue
            route_data = route.get("data")
            vault_routes.append(VaultRoute(**route_data))
        return vault_routes

    def _remove_route_from_vault(self, train_id: str) -> None:
        self.vault_client.secrets.kv.v1.delete_secret(
            path=train_id,
            mount_point="routes"
        )
        logger.info(f"Removed route for train {train_id} from vault")

    def _move_train(self, train_id: str, origin: str, dest: str, delete=True, outgoing: bool = False):
        """
        Moves a train and its associated artifacts from the origin project to the destination project

        :param train_id: identifier of the train
        :param origin: project identifier of the project the image currently resides in
        :param dest: project to move the image to
        :param delete: boolean controlling whether to delete the image or not
        :return:
        """

        if dest == UtilityStations.OUTGOING.value:
            url = f"{self.harbor_api_url}/projects/{dest}/repositories/{train_id}/artifacts"
            outgoing = True

        elif dest == UtilityStations.INCOMING.value:
            url = f"{self.harbor_api_url}/projects/{dest}/repositories/{train_id}/artifacts"

        elif dest == UtilityStations.INTEROP.value:
            url = f"{self.harbor_api_url}/projects/{dest}/repositories/{train_id}/artifacts"
            self._transfer_interop(train_id, origin)

        else:
            url = f"{self.harbor_api_url}/projects/station_{dest}/repositories/{train_id}/artifacts"

        if origin == UtilityStations.INCOMING.value:
            params_latest = {"from": f"{origin}/{train_id}:latest"}
            params_base = {"from": f"{origin}/{train_id}:base"}
        else:
            params_latest = {"from": f"station_{origin}/{train_id}:latest"}
            params_base = {"from": f"station_{origin}/{train_id}:base"}

        # Move base image
        logger.info("Moving train images...")
        icon = u'\u2713'
        if not outgoing:
            base_r = requests.post(url=url, headers=self.harbor_headers, auth=self.harbor_auth, params=params_base)
            try:
                base_r.raise_for_status()
            except Exception as e:
                print(base_r.text)
                logger.error(f"Train - {train_id} - Error moving base image: {e}")
                raise e

            logger.info(f"base: {icon}")

        # Move latest image
        latest_r = requests.post(url=url, headers=self.harbor_headers, auth=self.harbor_auth, params=params_latest)
        try:
            latest_r.raise_for_status()
        except Exception as e:
            print(latest_r.text)
            logger.error(f"Train - {train_id} - Error moving latest image: {e}")
            raise e

        logger.info(f"latest: {icon}")

        if delete:
            delete_url = f"{self.harbor_api_url}/projects/{origin}/repositories/{train_id}"
            r_delete = requests.delete(delete_url, auth=self.harbor_auth, headers=self.harbor_headers)
            logger.info(f"Deleted old artifacts \n {r_delete.text}")

    def _reset_train(self, train_id: str):
        # todo delete latest image and replace with base image
        # Get the stored route data from vault
        route = self.vault_client.secrets.kv.v1.read_secret(path=train_id, mount_point="routes")
        route = VaultRoute(**route.get("data"))
        # Find the train and move it back to incoming project
        self._find_train_and_reset(train_id)
        # check if the train exists in redis if so remove it
        if self.redis_store.exists(train_id):
            self.redis_store.remove_train_from_store(train_id)

        # Initialize the train again
        self.redis_store.register_train(route)

    def _find_train_and_reset(self, train_id: str):
        incoming_repo = UtilityStations.INCOMING.value
        search_result = self._find_train(train_id)
        if search_result:
            logger.debug("Found train in Harbor")
            # if the train exists in harbor and isn't in the utility projects, reset it
            # Todo reset from outgoing repo?
            for repo in search_result:
                if not UtilityStations.has_value(repo.get("project_name")):
                    logger.info(f"Found train in {repo.get('project_name')}, moving back to incoming")
                    self._move_train(train_id, repo.get("project_name"), incoming_repo, delete=True)

        # reset the latest artifact to the base version
        self._reset_latest_artifact(train_id)

    def _reset_latest_artifact(self, train_id: str, ):
        url = f"{self.harbor_api_url}/projects/{UtilityStations.INCOMING.value}/repositories/{train_id}/artifacts"
        params = {"from": f"{UtilityStations.INCOMING.value}/{train_id}:base"}

        tag_url = url + "/tags"

        print(requests.get(tag_url, headers=self.harbor_headers, auth=self.harbor_auth).text)

    def _find_train(self, train_id: str) -> List[dict]:
        # search for the train in harbor
        url = f"{self.harbor_api_url}/search"
        params = {"q": {train_id}}

        r = requests.get(url=url, params=params, headers=self.harbor_headers, auth=self.harbor_auth)
        if r.status_code == 200:
            data = r.json()
            print(data)
            if data["repository"]:
                return data["repository"]
            else:
                logger.error(f"Train {train_id} not found in harbor")
        else:
            logger.error(f"Error finding train {train_id} in harbor")
            logger.error(r.text)

    def start_train_for_demo_station(self, train_id: str, station_id: str, airflow_config: dict = None):
        LOGGER.info(f"Starting train for demo station {station_id}")
        repository = os.getenv("HARBOR_URL").split("//")[-1] + f"/station_{station_id}/{train_id}"

        payload = {
            "repository": repository,
            "tag": "latest"
        }
        # todo enable the use of different data sets
        volumes = {
            f"/opt/stations/station_{station_id}/station_data/cord_input.csv": {
                "bind": "/opt/train_data/cord_input.csv",
                "mode": "ro"
            }
        }
        payload["volumes"] = volumes

        if airflow_config:
            payload = {**payload, **airflow_config}

        body = {
            "conf": payload
        }
        demo_station: DemoStation = self.demo_stations[station_id]

        url = demo_station.api_endpoint() + "dags/run_pht_train/dagRuns"
        r = requests.post(url=url, auth=demo_station.auth(), json=body)

        r.raise_for_status()
        return r.json()

    def _get_demo_stations(self):
        url = f"{self.vault_url}/v1/demo-stations/metadata"

        r = requests.get(url=url, params={"list": True}, headers=self.vault_headers)
        r.raise_for_status()
        demo_stations = r.json()["data"]["keys"]

        for ds in demo_stations:
            demo_station_data = self.vault_client.secrets.kv.v2.read_secret(
                mount_point="demo-stations",
                path=ds
            )
            demo_station = DemoStation(**demo_station_data["data"]["data"])

            self.demo_stations[demo_station.id] = demo_station

    def _transfer_interop(self, train_id: str, origin: str):
        docker_client = docker.from_env()
