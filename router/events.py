from enum import Enum


class RouterEvents(Enum):
    """
    Enum for the events that can be sent to the router.
    """
    TRAIN_PUSHED = "trainPushed"
    TRAIN_BUILT = "trainBuilt"
    TRAIN_START = "startTrain"
    TRAIN_STOP = "stopTrain"
    TRAIN_STATUS = "trainStatus"


class RouterResponseEvents(Enum):
    """
    Enum for the responses that can be sent from the router.
    """
    STARTED = "trainStarted"
    STOPPED = "trainStopped"
    FAILED = "trainFailed"


class RouterErrorCodes(Enum):
    """
    Enum for the error codes that can be sent from the router.
    """
    TRAIN_NOT_FOUND = 0
    TRAIN_ALREADY_STARTED = 1
    TRAIN_ALREADY_STOPPED = 2
