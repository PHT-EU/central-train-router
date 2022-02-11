from dataclasses import dataclass
import json
from typing import Union

from router.events import RouterEvents, RouterResponseEvents, RouterErrorCodes


@dataclass
class RouterResponse:
    """
    Class for the responses that can be sent from the router.
    """
    event: RouterResponseEvents
    train_id: str
    message: str = None
    error_code: RouterErrorCodes = None

    def make_queue_message(self) -> bytes:
        message_dict = {
            "type": self.event.value,
            "data": {
                "trainId": self.train_id,
                "message": self.message,
                "errorCode": self.error_code.value if self.error_code else None,
            }
        }

        return json.dumps(message_dict).encode("utf-8")


@dataclass
class RouterCommand:
    """
    Class for parsing the commands that can be sent to the router in the message queue.
    """
    event_type: RouterEvents
    train_id: str
    project: str = None
    operator: str = None

    @classmethod
    def from_message(cls, message: Union[bytes, str, dict]) -> "RouterCommand":
        if isinstance(message, bytes) or isinstance(message, str):
            message_dict = json.loads(message)
        else:
            message_dict = message
        event_type = message_dict["type"]

        if event_type == RouterEvents.TRAIN_PUSHED.value:
            project, train_id = message_dict["data"]["repositoryFullName"].split("/")
            return cls(
                event_type=RouterEvents.TRAIN_PUSHED,
                train_id=train_id,
                project=project,
                operator=message_dict["data"]["operator"],
            )
        else:
            return cls(
                train_id=message_dict["data"]["id"],
                event_type=RouterEvents(message_dict["type"]),
            )
