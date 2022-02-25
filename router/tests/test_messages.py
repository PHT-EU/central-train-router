import json
import pytest

from router.messages import RouterCommand, RouterResponse
from router.events import RouterEvents, RouterResponseEvents, RouterErrorCodes


@pytest.fixture
def event_messages():
    train_id = "test-train"
    messages = {}

    for event in RouterEvents:
        if event == RouterEvents.TRAIN_PUSHED:
            messages[event.value] = {
                "type": event.value,
                "data": {
                    "operator": "test-operator",
                    "repositoryFullName": "test-repository/test-train",
                }
            }
        else:
            messages[event.value] = {
                "type": event.value,
                "data": {
                    "trainId": train_id
                }
            }

    return messages


@pytest.fixture
def system_build_message():
    message = {
        "type": RouterEvents.TRAIN_BUILT.value,
        "data": {
            "operator": "system",
            "repositoryFullName": "test-repository/test-train",
        }
    }
    return message


def test_parse_messages(event_messages, system_build_message):
    for message in event_messages.values():
        command = RouterCommand.from_message(message)
        assert command.event_type.value == message["type"]

        command = RouterCommand.from_message(json.dumps(message))
        assert command.event_type.value == message["type"]

        command = RouterCommand.from_message(json.dumps(message).encode("utf-8"))
        assert command.event_type.value == message["type"]
