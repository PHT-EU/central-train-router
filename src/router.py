from train_lib.clients import Consumer, PHTClient
from train_lib.clients.rabbitmq import LOG_FORMAT
import os
import redis
from dotenv import find_dotenv, load_dotenv
import requests
from typing import List
from pprint import pprint


class TrainRouter:
    def __init__(self):

        # Get access variables from the environment
        self.vault_url = os.getenv("VAULT_URL")
        self.vault_token = os.getenv("VAULT_TOKEN")
        self.harbor_api = os.getenv("HARBOR_API")
        self.harbor_user = os.getenv("HARBOR_USER")
        self.harbor_pw = os.getenv("HARBOR_PW")

        # Set up values for services
        self.redis = redis.Redis(decode_responses=True)
        self.vault_headers = {"X-Vault-Token": self.vault_token}
        self.harbor_headers = {'accept': 'application/json', 'Content-Type': 'application/json'}
        self.harbor_auth = (self.harbor_user, self.harbor_pw)

    def sync_routes_with_vault(self):
        routes = self._get_all_routes_from_vault()

        # Iterate over all routes and add them to redis if they dont exist
        for train_id in routes:
            if not self.redis.exists(f"{train_id}-stations"):
                data = self.get_route_data_from_vault(train_id)
                self._add_route_to_redis(data)
            else:
                print(f"Route for train {train_id}, already exists")

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

        train_id = route["repositorySuffix"]
        stations = route["harborProjects"]
        # TODO maybe shuffle the participants
        # Store
        self.redis.rpush(f"{train_id}-stations", *stations)
        self.redis.set(f"{train_id}-type", "periodic" if route["periodic"] else "linear")


    def get_route_data_from_vault(self, train_id: str) -> dict:
        """
        Get the route data for the given train_id from the vault REST api

        :param train_id:
        :return:
        """
        url = f"{self.vault_url}/v1/kv-pht-routes/data/{train_id}"
        r = requests.get(url, headers=self.vault_headers)

        return r.json()["data"]["data"]

    def process_route(self, train_id: str):
        route = self.redis.lrange()
        pass

    def move_image(self, train_id: str, origin: str, dest: str):
        pass

    def scan_harbor(self):
        pass

    def scan_harbor_project(self, project_id: str) -> dict:
        """
        Scan a harbor projects listing all the repositories in the image

        :param project_id: identifier of the project to scan
        :return:
        """
        url = self.harbor_api + f"/projects/{project_id}/repositories"
        r = requests.get(url, headers=self.harbor_headers, auth=self.harbor_auth)

        return r.json()




if __name__ == '__main__':
    load_dotenv(find_dotenv())
    tr = TrainRouter()
    # tr.redis.delete("route-1")
    # tr.redis.lpush("route-1", *[1,2,3])
    # print(tr.redis.lrange("route-1", 0, -1))

    train_id = "00673752-7126-4a84-8d25-99fd39fb273d"

    # print(tr.get_route_from_vault(train_id))
    # tr.scan_harbor_project("1")
    tr.sync_routes_with_vault()