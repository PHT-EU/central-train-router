from typing import Union
from dotenv import load_dotenv, find_dotenv
import os
import json
import logging
import pika
from enum import Enum

from router import TrainRouter
from train_lib.clients import Consumer, PHTClient
from train_lib.clients.rabbitmq import LOG_FORMAT

LOGGER = logging.getLogger(__name__)


class RouterEvents(Enum):
    """
    Enum for the events that can be sent to the router.
    """
    TRAIN_PUSHED = "trainPushed"
    TRAIN_BUILT = "trainBuilt"
    TRAIN_START = "startTrain"
    TRAIN_STOP = "stopTrain"


class RouterResponseEvents(Enum):
    """
    Enum for the responses that can be sent from the router.
    """
    STARTED = "trainStarted"
    STOPPED = "trainStopped"
    ERROR = "error"
    FAILED = "trainFailed"



# todo errors for functions


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
        # determine auto start mode
        self.auto_start = os.getenv("AUTO_START") == "true"

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
        if msg["type"] == RouterEvents.TRAIN_PUSHED.value:
            # todo improve this
            project, train_id = msg["data"]["repositoryFullName"].split("/")

            # Ignore push events by system services (such as the TR itself)
            if not msg["data"].get("operator", "system") == "system":
                LOGGER.info(f"Moving train: {train_id}")
                self.router.process_train(train_id, project)

            else:
                LOGGER.info(f"System Operation detected -> ignoring push event")

        # Perform the initial setup for a train (set up redis k/v pairs)
        elif msg["type"] == RouterEvents.TRAIN_BUILT.value:

            train_id = msg["data"]["trainId"]
            LOGGER.info(f"Adding route for new train {train_id}")
            self.router.get_route_data_from_vault(train_id)

            if self.auto_start:
                self.start_train(train_id)

        # Start the train by setting its status in redis
        elif msg["type"] == RouterEvents.TRAIN_START.value:
            train_id = msg["data"]["trainId"]
            self.start_train(train_id)

        # Stop the train
        elif msg["type"] == RouterEvents.TRAIN_STOP.value:
            train_id = msg["data"]["trainId"]
            LOGGER.info(f"Stopping train {train_id}.")
            self.router.update_train_status(train_id, "stopped")
            self.publish_events_for_train(train_id=train_id, event_type="trainStopped")

        else:
            train_id = msg["data"]["trainId"]
            LOGGER.info(f"Invalid event {msg['type']}")
            self.publish_events_for_train(train_id=train_id, event_type="trainFailed")

    def publish_events_for_train(self, train_id: str, event_type: str, message_body: str = None, exchange: str = "pht",
                                 exchange_type: str = "topic", routing_key: str = "ui.tr.event"):

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

    def start_train(self, train_id: str):
        LOGGER.info(f"Starting train {train_id}.")
        self.router.update_train_status(train_id, "running")
        self.router.process_train(train_id, "pht_incoming")
        self.publish_events_for_train(train_id=train_id, event_type="trainStarted")


def main():
    load_dotenv(find_dotenv())
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    tr_consumer = TRConsumer(os.getenv("AMPQ_URL"), "", routing_key="tr")
    tr_consumer.run()


if __name__ == '__main__':
    main()
