FROM ubuntu
MAINTAINER michael.graf@uni-tuebingen.de
# update python version and replace python with python 3
RUN apt -y update && apt-get -y install software-properties-common && \
    add-apt-repository ppa:deadsnakes/ppa && apt -y update && apt -y install git && \
    apt-get install -y python3.9 && apt install python-is-python3 && apt install -y python3-pip && \
    rm -rf /var/lib/apt/lists && \
    pip install pipenv==2021.5.29 && \
    rm -rf /var/lib/apt/lists

WORKDIR /opt/train-router/

COPY Pipfile /opt/train-router/Pipfile
COPY Pipfile.lock /opt/train-router/Pipfile.lock

RUN pipenv install --system --deploy --ignore-pipfile
RUN pip install git+https://github.com/PHT-Medic/train-container-library.git

COPY router /opt/train-router/router

CMD ["python", "-u", "/opt/train-router/router/TRConsumer.py"]
