from train_lib.clients import Consumer, PHTClient
from train_lib.clients.rabbitmq import LOG_FORMAT
import os
import redis
from dotenv import find_dotenv, load_dotenv
import requests
from typing import List
from pprint import pprint
import random


class TrainRouter:
    def __init__(self):

        # Get access variables for external services from environment variables
        self.vault_url = os.getenv("VAULT_URL")
        self.vault_token = os.getenv("VAULT_TOKEN")
        self.harbor_api = os.getenv("HARBOR_API")
        self.harbor_user = os.getenv("HARBOR_USER")
        self.harbor_pw = os.getenv("HARBOR_PW")

        # Configure redis instance if host is not available in env var use default localhost
        self.redis = redis.Redis(host=os.getenv("REDIS_HOST", None), decode_responses=True)

        # Set up header and auth for services
        self.vault_headers = {"X-Vault-Token": self.vault_token}
        self.harbor_headers = {'accept': 'application/json', 'Content-Type': 'application/json'}
        self.harbor_auth = (self.harbor_user, self.harbor_pw)

    def scan_harbor_project(self, project_id: str):
        """
        Scan a harbor projects listing all the repositories in the image

        :param project_id: identifier of the project to scan
        :return:
        """
        url = self.harbor_api + f"/projects/{project_id}/repositories"
        r = requests.get(url, headers=self.harbor_headers, auth=self.harbor_auth)
        repos = r.json()

        for repo in repos:
            train_id = repo["name"].split("/")[-1]
            if self._check_artifact_label(project_id, train_id):
                self.process_train(train_id)

    def process_train(self, train_id: str):
        """
        Processes a train image tagged with the pht_next label according the route stored in redis

        :param train_id:
        :return:
        """

        route_type = self.redis.get(f"{train_id}-type")
        # TODO perform different actions based on route type
        print(train_id, route_type)

        # If the route exists move to next station project

        if self.redis.exists(f"{train_id}-route"):
            next_station_id = self.redis.rpop(f"{train_id}-route")
            print(next_station_id)
        # otherwise move to pht_outgoing
        else:
            # TODO delete route from vault and redis
            pass

    def sync_routes_with_vault(self):
        """
        Gets all routes stored in vault and compares them with the ones stored in redis, if a route does not exist in
        redis it will be added.

        :return:
        """

        routes = self._get_all_routes_from_vault()

        # Iterate over all routes and add them to redis if they dont exist
        for train_id in routes:
            self.redis.delete(f"{train_id}-stations", f"{train_id}-type")
            if not self.redis.exists(f"{train_id}-stations"):
                data = self.get_route_data_from_vault(train_id)
                self._add_route_to_redis(data)
            else:
                print(f"Route for train {train_id} already exists")

    def _get_all_routes_from_vault(self) -> List[str]:
        """
        Queries the kv-pht-routes secret engines and returns a list of the keys (train ids) stored in vault
        :return:
        """

        url = f"{self.vault_url}/v1/kv-pht-routes/metadata"

        r = requests.get(url=url, params={"list": True}, headers=self.vault_headers)
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
        self.redis.rpush(f"{train_id}-route", *stations)
        self.redis.set(f"{train_id}-type", "periodic" if route["periodic"] else "linear")
        # TODO store the number of epochs somewhere/ also needs to be set when specifying periodic routes

    def get_route_data_from_vault(self, train_id: str) -> dict:
        """
        Get the route data for the given train_id from the vault REST api

        :param train_id:
        :return:
        """
        url = f"{self.vault_url}/v1/kv-pht-routes/data/{train_id}"
        r = requests.get(url, headers=self.vault_headers)

        return r.json()["data"]["data"]

    def _move_train(self, train_id: str, origin: str, dest: str, delete=True):
        # TODO move base and latest image
        url = f"{self.harbor_api}/projects/{dest}/repositories/{train_id}/artifacts"
        params_latest = {"from": f"{origin}/{train_id}:latest"}
        params_base = {"from": f"{origin}/{train_id}:base"}

        # Move base image
        base_r = requests.post(url=url, headers=self.harbor_headers, auth=self.harbor_auth, params=params_base)
        print(base_r.text)

        # Move latest image
        latest_r = requests.post(url=url, headers=self.harbor_headers, auth=self.harbor_auth, params=params_latest)
        print(latest_r.text)
        if delete:
            delete_url = f"{self.harbor_api}/projects/{origin}/repositories/{train_id}/artifacts/"
            r_latest = requests.delete(delete_url + "latest")
            print(r_latest.text)
            r_base = requests.delete(delete_url + "base")






    def _check_artifact_label(self, project_id: str, train_id: str, tag: str = "latest"):
        url = f'{self.harbor_api}/projects/{project_id}/repositories/{train_id}/artifacts/{tag}'
        r = requests.get(url=url, headers=self.harbor_headers, auth=self.harbor_auth, params={"with_label": True})
        labels = r.json()["labels"]
        if labels and not any(d["name"] == "pht_next" for d in labels):
            print("Found next label")
            return True
        else:
            return False


if __name__ == '__main__':
    load_dotenv(find_dotenv())
    tr = TrainRouter()
    # tr.redis.delete("route-1")
    # tr.redis.lpush("route-1", *[1,2,3])
    # print(tr.redis.lrange("route-1", 0, -1))

    train_id = "a3ea25fd-8a66-4f00-b193-ac8d5745f44c"

    # print(tr.get_route_from_vault(train_id))
    # print(tr.scan_harbor_project("1"))
    # tr.sync_routes_with_vault()
    tr._move_train(train_id=train_id, origin="1", dest="2")
