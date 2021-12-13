[![Build and push image](https://github.com/PHT-Medic/central-train-router/actions/workflows/CI.yml/badge.svg)](https://github.com/PHT-Medic/central-train-router/actions/workflows/CI.yml)
[![CodeQL](https://github.com/PHT-Medic/central-train-router/actions/workflows/codeql-analysis.yml/badge.svg)](https://github.com/PHT-Medic/central-train-router/actions/workflows/codeql-analysis.yml)
[![Vulnerability Scan](https://github.com/PHT-Medic/central-train-router/actions/workflows/image_scan.yml/badge.svg)](https://github.com/PHT-Medic/central-train-router/actions/workflows/image_scan.yml)
# PHT Train Router
Python Implementation of the PHT Train Router service for moving docker images (Trains)
along the Route selected in the User Interface.
The service will access the routes stored in vault and store them in redis, for further
processing. Only trains (or images) pushed by station will be processed by the service, with system operations (such as
when an image is built by the train builder) are ignored.
After completing a received command the service, will post status updates into the UI message queue.

## Event Processing
To process events such as when a train build is finished and pushed back into the station repository,
the Train Router listens to events in a dedicated RabbitMQ message queue.
The following events/commands are supported:
- `trainBuilt` is triggered when a train is created, and the TR will query the trains route from vault and and store it in redis
    for further processing.
- `trainPushed` is triggered when a station pushes a finished train back into their harbor project, if there are any steps
  in the route, the TR will move the train image to the next stop in the route, otherwise it will be moved to `pht_outgoing`.
- `startTrain` is triggered when a train is started via the central user interface, the TR will then move the train image
    from the 'pht_incoming' project to the first stop in the stored route
- `stopTrain` is triggered by the central user interface when a train is stopped, the TR will temporarily stop the processing
    of the train router and ignore any further commands until the train is restarted.

The same message broker is used to communicate the train status with the user interface after the command has been processed.

## Running the service
1. Edit the connection environment variables in the docker-compose file to match your 
   configuration
    ```
    - VAULT_TOKEN=<token>
    - VAULT_URL=https://vault.pht.medic.uni-tuebingen.de
    - HARBOR_API=https://harbor.personalhealthtrain.de/api/v2.0
    - HARBOR_USER=<harbor_user>
    - HARBOR_PW=<harbor_pw>
    - UI_TRAIN_API=http://pht-ui.personalhealthtrain.de/api/pht/trains/
    - AMPQ_URL=<ampq_url>
    ```
2. Start the service by running `docker-compose up -d`

### Credits
[Icon](https://www.flaticon.com/authors/eucalyp)

