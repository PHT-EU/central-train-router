from train_lib.clients import Consumer, PHTClient
from train_lib.clients.rabbitmq import LOG_FORMAT
from router import TrainRouter
from dotenv import load_dotenv, find_dotenv
import os
import json
import logging

LOGGER = logging.getLogger(__name__)


class TRConsumer(Consumer):
    def __init__(self, amqp_url: str, queue: str = "", public_key_path: str = None, routing_key: str = None):
        super().__init__(amqp_url, queue, routing_key=routing_key)
        # self.builder = TrainBuilder()
        # self.pht_client = PHTClient(ampq_url=amqp_url, api_url=os.getenv("UI_TRAIN_API"),
        #                             vault_url=os.getenv("vault_url"), vault_token=os.getenv("vault_token"))
        #
        # if public_key_path:
        #     with open(public_key_path, "r") as public_key_file:
        #         self.pk = public_key_file.read()

        # Set auto reconnect to true
        self.router = TrainRouter()
        self.auto_reconnect = True
        # Configure routing key
        self.ROUTING_KEY = "tr"

    def run(self):
        self.router.sync_routes_with_vault()
        super().run()

    def on_message(self, _unused_channel, basic_deliver, properties, body):
        try:
            message = json.loads(body)
            # print(json.dumps(message, indent=2))
        except:
            # self.pht_client.publish_message_rabbit_mq(
            #     {"type": "trainBuildFailed", "data": {"message": "Malformed JSON"}},
            #     routing_key="ui")
            LOGGER.info("Malformed json input")
            super().on_message(_unused_channel, basic_deliver, properties, body)
            return
        # LOGGER.info(f"Received message: \n {message}")
        self.process_message(message)
        super().on_message(_unused_channel, basic_deliver, properties, body)

    def process_message(self, msg: dict):
        if msg["event"] == "trainPush":
            self.router.process_train(msg["trainId"], msg["station"])
        else:
            LOGGER.info(f"Invalid event {msg['event']}")


def main():
    load_dotenv(find_dotenv())
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    tr_consumer = TRConsumer(os.getenv("AMPQ_URL"), "", routing_key="tr")
    tr_consumer.run()


if __name__ == '__main__':
    main()
