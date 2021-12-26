import json
import os
import redis
import requests
from typing import List
import random
import logging
from dataclasses import dataclass
import hvac
from dotenv import load_dotenv, find_dotenv
from requests import HTTPError
from loguru import logger

from router.messages import RouterCommand, RouterResponse

LOGGER = logging.getLogger(__name__)


class TrainRouter:
    vault_url: str
    vault_token: str
    vault_client: hvac.Client
    harbor_api_url: str
    harbor_user: str
    harbor_password: str
    harbor_headers: dict
    harbor_auth: tuple
    redis_host: str
    redis: redis.Redis
    auto_start: bool = False
    demo_mode: bool = False
    demo_stations: dict = None

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
        self.vault_client = hvac.Client(url=self.vault_url, token=self.vault_token)
        logger.info("Successfully connected to Vault")

        logger.info("Setting up harbor connection, with environment variables")
        self.harbor_api_url = os.getenv("HARBOR_API")
        if not self.harbor_api_url:
            raise ValueError("HARBOR_API not set in environment variables")
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
            r.raise_for_status()
        except HTTPError as e:
            logger.error("Harbor connection failed with error: {}", e)
        logger.info("Successfully connected to Harbor")

        logger.info("Setting up redis connection, with environment variables")
        self.redis_host = os.getenv("REDIS_HOST")
        if not self.redis_host:
            raise ValueError("REDIS_HOST not set in environment variables")
        self.redis = redis.Redis(host=self.redis_host, decode_responses=True)
        logger.info("Successfully connected to Redis")

        # class variables for running train router in demonstration mode
        self.auto_start = os.getenv("AUTO_START") == "true"
        self.demo_mode = os.getenv("DEMONSTRATION_MODE") == "true"
        if self.demo_mode:
            self.demo_stations = {}
            logger.info("Demonstration mode detected, attempting to load demo stations")
            self._get_demo_stations()

    def process_command(self, command: RouterCommand) -> RouterResponse:
        pass

    def process_train(self, train_id: str, current_project: str):
        """
        Processes a train image tagged with the pht_next label according the route stored in redis

        :param current_project: the harbor project the train currently resides in
        :param train_id: identifier of the train repository
        :return:
        """

        route_type = self.redis.get(f"{train_id}-type")
        # TODO perform different actions based on route type
        # If the route exists move to next station project

        if route_type:
            if self.redis.get(f"{train_id}-status") == "running":
                if self.redis.exists(f"{train_id}-route"):
                    next_station_id = self.redis.rpop(f"{train_id}-route")
                    LOGGER.info(f"Moving train {train_id} from {current_project} to station_{next_station_id}")
                    self._move_train(train_id, origin=current_project, dest=next_station_id)

                    # if demo mode is enabled immediately trigger the execution of the train once it is moved
                    if self.demo_mode:
                        try:
                            response = self.start_train_for_demo_station(train_id, next_station_id)
                            LOGGER.info(f"Successfully started train {train_id} for station {next_station_id}")
                            LOGGER.info(response)
                        except HTTPError as e:
                            LOGGER.error(f"Error starting train {train_id} for station {next_station_id}")
                            LOGGER.error(e)

                # otherwise move to pht_outgoing
                else:
                    LOGGER.info(f"No more steps in the route moving {train_id} to pht_outgoing")
                    self._move_train(train_id, origin=current_project, dest="pht_outgoing", outgoing=True)
                    self._clean_up_finished_train(train_id)
            else:
                LOGGER.info(f"Train {train_id} is stopped. Ignoring push event")

        else:
            LOGGER.info(f"Image {train_id} not registered. Ignoring...")

    def update_train_status(self, train_id: str, status: str):
        """
        Update the train status of the train with the given id in redis with a new status

        :param train_id: identifier of the train
        :param status: the new status to be set in redis
        :return:
        """
        self.redis.set(f"{train_id}-status", status)

    def _clean_up_finished_train(self, train_id: str):
        """
        Removes the stored values from redis and vault once a train is finished and moved to the pht_outgoing project

        :param train_id:
        :return:
        """
        # Remove the entries for the train from redis
        self.redis.delete(f"{train_id}-route")
        self.redis.delete(f"{train_id}-stations")
        self.redis.delete(f"{train_id}-type")
        self.redis.delete(f"{train_id}-status")
        # Remove route from vault storage
        self._remove_route_from_vault(train_id)

    def sync_routes_with_vault(self):
        """
        Gets all routes stored in vault and compares them with the ones stored in redis, if a route does not exist in
        redis it will be added.

        :return:
        """

        LOGGER.info("Syncing redis routes with vault storage")
        try:
            routes = self._get_all_routes_from_vault()

            # Iterate over all routes and add them to redis if they dont exist
            for train_id in routes:
                # self.redis.delete(f"{train_id}-stations", f"{train_id}-type")
                if not self.redis.exists(f"{train_id}-stations"):
                    LOGGER.debug(f"Adding train {train_id} to redis storage.")
                    self.get_route_data_from_vault(train_id)
                else:
                    LOGGER.info(f"Route for train {train_id} already exists")
            LOGGER.info("Synchronized redis")
        except:
            LOGGER.error(f"Error syncing with vault")
            LOGGER.exception("Traceback")

    def _get_all_routes_from_vault(self) -> List[str]:
        """
        Queries the kv-pht-routes secret engines and returns a list of the keys (train ids) stored in vault
        :return:
        """

        url = f"{self.vault_url}/v1/kv-pht-routes/metadata"

        r = requests.get(url=url, params={"list": True}, headers=self.vault_headers)
        r.raise_for_status()
        routes = r.json()["data"]["keys"]

        return routes

    def _add_route_to_redis(self, route: dict):
        """
        Takes the route data received from vault and stores it in redis for processing
        :param route: dictionary containing the participating stations, route type and train id
        :return:
        """

        train_id = route["repositorySuffix"]
        stations = route["harborProjects"]
        # Store the participating stations as well as the route type separately
        print(stations)

        if stations:
            self.redis.rpush(f"{train_id}-stations", *stations)
        # Shuffle the stations to create a randomized route
        random.shuffle(stations)
        self.redis.set(f"{train_id}-status", "stopped")
        self.redis.rpush(f"{train_id}-route", *stations)
        self.redis.set(f"{train_id}-type", "periodic" if route["periodic"] else "linear")

        # TODO store the number of epochs somewhere/ also needs to be set when specifying periodic routes

    def get_route_data_from_vault(self, train_id: str):
        """
        Get the route data for the given train_id from the vault REST api

        :param train_id:
        :return:
        """
        try:
            url = f"{self.vault_url}/v1/kv-pht-routes/data/{train_id}"
            r = requests.get(url, headers=self.vault_headers)
            r.raise_for_status()
            route = r.json()["data"]["data"]
            # Add the received route from redis
            self._add_route_to_redis(route)

        except:
            LOGGER.error(f"Error getting routes from vault for train {train_id}")
            LOGGER.exception("Traceback")

    def _remove_route_from_vault(self, train_id: str):
        url = f"{self.vault_url}/v1/kv-pht-routes/data/{train_id}"
        r = requests.delete(url, headers=self.vault_headers)
        LOGGER.info(r.text)

    def _move_train(self, train_id: str, origin: str, dest: str, delete=True, outgoing: bool = False):
        """
        Moves a train and its associated artifacts from the origin project to the destination project

        :param train_id: identifier of the train
        :param origin: project identifier of the project the image currently resides in
        :param dest: project to move the image to
        :param delete: boolean controlling whether to delete the image or not
        :return:
        """

        if dest == "pht_outgoing":
            url = f"{self.harbor_api}/projects/{dest}/repositories/{train_id}/artifacts"
        else:
            url = f"{self.harbor_api}/projects/station_{dest}/repositories/{train_id}/artifacts"
        params_latest = {"from": f"{origin}/{train_id}:latest"}
        params_base = {"from": f"{origin}/{train_id}:base"}

        # Move base image
        LOGGER.info("Moving images")

        if not outgoing:
            base_r = requests.post(url=url, headers=self.harbor_headers, auth=self.harbor_auth, params=params_base)
            LOGGER.info(f"base:  {base_r.text}")

        # Move latest image
        latest_r = requests.post(url=url, headers=self.harbor_headers, auth=self.harbor_auth, params=params_latest)
        LOGGER.info(f"latest:  {latest_r.text}")

        if delete:
            delete_url = f"{self.harbor_api}/projects/{origin}/repositories/{train_id}"
            r_delete = requests.delete(delete_url, auth=self.harbor_auth, headers=self.harbor_headers)
            LOGGER.info(f"Deleting old artifacts \n {r_delete.text}")

    def _check_artifact_label(self, project_id: str, train_id: str, tag: str = "latest"):
        """
        Check if a train image in a project contains the pht_next label
        :param project_id: harbor project the train image is located in
        :param train_id: identifier of the train
        :param tag: the image to check for, defaults to latest
        :return:
        """
        url = f'{self.harbor_api}/projects/{project_id}/repositories/{train_id}/artifacts/{tag}'
        r = requests.get(url=url, headers=self.harbor_headers, auth=self.harbor_auth, params={"with_label": True})
        labels = r.json()["labels"]
        if labels and not any(d["name"] == "pht_next" for d in labels):
            print("Found next label")
            return True
        else:
            return False

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


if __name__ == '__main__':
    load_dotenv(find_dotenv())
    router = TrainRouter()
    router.start_train_for_demo_station("hello", "1")
