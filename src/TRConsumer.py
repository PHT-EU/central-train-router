from typing import Union

from train_lib.clients import Consumer, PHTClient
from train_lib.clients.rabbitmq import LOG_FORMAT
from router import TrainRouter
from dotenv import load_dotenv, find_dotenv
import os
import json
import logging
import pika

LOGGER = logging.getLogger(__name__)


class TRConsumer(Consumer):
    def __init__(self, ampq_url: str, queue: str = "", routing_key: str = None):
        super().__init__(ampq_url, queue, routing_key=routing_key)
        self.ampq_url = ampq_url

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
        """
        Filter the type and info from the received message from rabbit mq, and perform actions using the train router
        accordingly.

        :param msg:
        :return:
        """

        if type(msg) == str:
            msg = json.loads(msg)

        # If a train is pushed by a station or user process if using the stored routed
        if msg["type"] == "trainPushed":
            # todo improve this
            project, train_id = msg["data"]["repositoryFullName"].split("/")

            # Ignore push events by system services (such as the TR itself)
            if not msg["data"].get("operator", "system") == "system":
                LOGGER.info(f"Moving train: {train_id}")
                self.router.process_train(train_id, project)

            else:
                LOGGER.info(f"System Operation detected -> ignoring push event")

        # Perform the initial setup for a train (set up redis k/v pairs)
        elif msg["type"] == "trainBuilt":

            train_id = msg["data"]["trainId"]
            LOGGER.info(f"Adding route for new train {train_id}")
            self.router.get_route_data_from_vault(train_id)

        # Start the train by setting its status in redis
        elif msg["type"] == "startTrain":

            train_id = msg["data"]["trainId"]
            LOGGER.info(f"Starting train {train_id}.")
            self.router.update_train_status(train_id, "running")
            self.router.process_train(train_id, "pht_incoming")
            self.publish_events_for_train(train_id=train_id, event_type="trainStarted")

        # Stop the train
        elif msg["type"] == "stopTrain":
            train_id = msg["data"]["trainId"]
            LOGGER.info(f"Stopping train {train_id}.")
            self.router.update_train_status(train_id, "stopped")

        else:
            LOGGER.info(f"Invalid event {msg['type']}")

    def publish_events_for_train(self, train_id: str, event_type: str, message_body: str = None, exchange: str = "pht",
                                 exchange_type: str = "topic", routing_key: str = "ui.tr.events"):

        message = {
            "type": event_type,
            "data": {
                "trainId": train_id,
                "message": message_body
            }
        }
        connection = pika.BlockingConnection(pika.URLParameters(self.ampq_url))
        channel = connection.channel()
        channel.exchange_declare(exchange=exchange, exchange_type=exchange_type, durable=True)
        json_message = json.dumps(message).encode("utf-8")

        channel.basic_publish(exchange=exchange, routing_key=routing_key, body=json_message)
        LOGGER.info(" [x] Sent %r" % json_message)
        connection.close()


def main():
    load_dotenv(find_dotenv())
    print(os.getenv("VAULT_URL"))
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    tr_consumer = TRConsumer(os.getenv("AMPQ_URL"), "", routing_key="tr")
    tr_consumer.run()


if __name__ == '__main__':
    main()
