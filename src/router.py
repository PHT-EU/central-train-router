from train_lib.clients import Consumer, PHTClient
from train_lib.clients.rabbitmq import LOG_FORMAT
import os
import redis
from dotenv import find_dotenv, load_dotenv
import requests
from typing import List
from pprint import pprint
import random
import threading
import time
import logging
import traceback

LOGGER = logging.getLogger(__name__)


class TrainRouter:
    def __init__(self):

        # Get access variables for external services from environment variables
        self.vault_url = os.getenv("VAULT_URL")
        self.vault_token = os.getenv("VAULT_TOKEN")
        self.harbor_api = os.getenv("HARBOR_API")
        self.harbor_user = os.getenv("HARBOR_USER")
        self.harbor_pw = os.getenv("HARBOR_PW")

        if self.vault_url[-1] == "/":
            self.vault_url = self.vault_url[:-1]

        # TODO get the registered projects from somewhere
        # self.pht_projects = ["1", "2", "3", "pht_incoming"]
        self.pht_projects = ["1", "pht_incoming"]

        # Configure redis instance if host is not available in env var use default localhost
        self.redis = redis.Redis(host=os.getenv("REDIS_HOST", None), decode_responses=True)

        # Set up header and auth for services
        self.vault_headers = {"X-Vault-Token": self.vault_token}
        self.harbor_headers = {'accept': 'application/json', 'Content-Type': 'application/json'}
        self.harbor_auth = (self.harbor_user, self.harbor_pw)
        self.auto_start = os.getenv("AUTO_START")

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

                # otherwise move to pht_outgoing
                else:
                    LOGGER.info(f"No more steps in the route moving {train_id} to pht_outgoing")
                    self._move_train(train_id, origin=current_project, dest="pht_outgoing")
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
        self.redis.rpush(f"{train_id}-stations", *stations)
        # Shuffle the stations to create a randomized route
        random.shuffle(stations)
        self.redis.rpush(f"{train_id}-status", "stopped")
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

    def _move_train(self, train_id: str, origin: str, dest: str, delete=True):
        """
        Moves a train and its associated artifacts from the origin project to the destination project

        :param train_id: identifier of the train
        :param origin: project identifier of the project the image currently resides in
        :param dest: project to move the image to
        :param delete: boolean controlling wether to delete the image or not
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
        base_r = requests.post(url=url, headers=self.harbor_headers, auth=self.harbor_auth, params=params_base)
        LOGGER.info(f"base:  {base_r.text}")

        # Move latest image
        latest_r = requests.post(url=url, headers=self.harbor_headers, auth=self.harbor_auth, params=params_latest)
        LOGGER.info(f"latest:  {latest_r.text}")
        # remove pht next label
        label_url = f"{self.harbor_api}/projects/{dest}/repositories/{train_id}/artifacts/latest/labels/2"

        label_r = requests.delete(label_url, headers=self.harbor_headers, auth=self.harbor_auth)
        LOGGER.info(f"Removing pht_next label: {label_r.text}")

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
