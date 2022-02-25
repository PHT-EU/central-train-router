from typing import Union
from dotenv import load_dotenv, find_dotenv
import os
import json
import logging
import pika
from loguru import logger

from router.messages import RouterResponse, RouterCommand
from router.train_router import TrainRouter
from train_lib.clients import Consumer
from train_lib.clients.rabbitmq import LOG_FORMAT

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

    def run(self):
        super().run()

    def on_message(self, _unused_channel, basic_deliver, properties, body):
        try:
            message = json.loads(body)
            # print(json.dumps(message, indent=2))
        except json.JSONDecodeError:
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
        # parse message and command
        if isinstance(msg, str) or isinstance(msg, bytes):
            msg = json.loads(msg)
        print(msg)
        logger.debug(f"Received Message: {msg}")

        command = RouterCommand.from_message(msg)

        # perform requested action
        response = self.router.process_command(command)
        # publish response
        self.publish_events_for_train(response)

    def publish_events_for_train(self, response: RouterResponse, exchange: str = "pht",
                                 exchange_type: str = "topic", routing_key: str = "ui.tr.event"):

        connection = pika.BlockingConnection(pika.URLParameters(self.ampq_url))
        channel = connection.channel()
        channel.exchange_declare(exchange=exchange, exchange_type=exchange_type, durable=True)
        json_message = response.make_queue_message()
        channel.basic_publish(exchange=exchange, routing_key=routing_key, body=json_message)
        LOGGER.info(" [x] Sent %r" % json_message)
        connection.close()


def main():
    load_dotenv(find_dotenv())
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    tr_consumer = TRConsumer(os.getenv("AMQP_URL"), "", routing_key="tr")
    tr_consumer.run()


if __name__ == '__main__':
    main()
