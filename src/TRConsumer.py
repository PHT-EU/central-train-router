from typing import Union

from train_lib.clients import Consumer, PHTClient
from train_lib.clients.rabbitmq import LOG_FORMAT
from router import TrainRouter
from dotenv import load_dotenv, find_dotenv
import os
import json
import logging

LOGGER = logging.getLogger(__name__)


class TRConsumer(Consumer):
    def __init__(self, amqp_url: str, queue: str = "", routing_key: str = None):
        super().__init__(amqp_url, queue, routing_key=routing_key)

        # Set auto reconnect to true
        self.router = TrainRouter()
        self.auto_reconnect = True
        # Configure routing key
        self.ROUTING_KEY = routing_key
        self.router.sync_routes_with_vault()

    def run(self):
        super().run()

    def on_message(self, _unused_channel, basic_deliver, properties, body):
        try:
            message = json.loads(body)
            # print(json.dumps(message, indent=2))
        except:
            LOGGER.error("Malformed json input")
            super().on_message(_unused_channel, basic_deliver, properties, body)
        self.process_message(message)
        super().on_message(_unused_channel, basic_deliver, properties, body)

    def process_message(self, msg: Union[dict, str]):

        if type(msg) == str:
            msg = json.loads(msg)
        if msg["type"] == "PUSH_ARTIFACT":
            project, train_id = msg["data"]["repositoryFullName"].split("/")
            LOGGER.info(f"Moving train: {train_id}")
            self.router.process_train(train_id, project)
        elif msg["type"] == "TRAIN_BUILT":

            train_id = msg["data"]["trainId"]
            LOGGER.info(f"Adding route for new train {train_id}")
            self.router.get_route_data_from_vault(train_id)
        else:
            LOGGER.info(f"Invalid event {msg['type']}")


def main():
    load_dotenv(find_dotenv())
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    tr_consumer = TRConsumer(os.getenv("AMPQ_URL"), "", routing_key="tr.harbor")
    tr_consumer.run()


if __name__ == '__main__':
    main()
