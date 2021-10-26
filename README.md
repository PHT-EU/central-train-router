[![Build and push image](https://github.com/PHT-Medic/central-train-router/actions/workflows/CI.yml/badge.svg)](https://github.com/PHT-Medic/central-train-router/actions/workflows/CI.yml)
[![CodeQL](https://github.com/PHT-Medic/central-train-router/actions/workflows/codeql-analysis.yml/badge.svg)](https://github.com/PHT-Medic/central-train-router/actions/workflows/codeql-analysis.yml)
[![Vulnerability Scan](https://github.com/PHT-Medic/central-train-router/actions/workflows/image_scan.yml/badge.svg)](https://github.com/PHT-Medic/central-train-router/actions/workflows/image_scan.yml)
# PHT Train Router
Python Implementation of the PHT Train Router service for moving docker images (Trains)
along the Route selected in the User Interface.  
The service will access the routes stored in vault and store them in redis, for further
processing. 

To process events such as when a train is finished and pushed back into the station repository,
the Train Router processes events in a RabbitMQ message queue.
Currently two events are supported:
- `trainCreated` is triggered when a train is created, and the TR will query the trains route from vault and move the
  train image from the `pht_incoming` project to the first stop in the stored route
- `trainPushed` is triggered when a station pushes a finished train back into their harbor project

The same message broker is used to communicate the train status with the user interface



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

