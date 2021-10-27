FROM ubuntu
MAINTAINER michael.graf@uni-tuebingen.de
# update python version and replace python with python 3
RUN apt -y update && apt-get -y install software-properties-common
RUN add-apt-repository ppa:deadsnakes/ppa && apt -y update && apt -y install git && \
    apt-get install -y python3.8 && apt install python-is-python3 && apt install -y python3-pip && \
    rm -rf /var/lib/apt/lists && \
    pip install pipenv

WORKDIR /opt/train-router/

COPY Pipfile /opt/train-router/Pipfile
COPY Pipfile.lock /opt/train-router/Pipfile.lock

RUN pipenv install --system --deploy --ignore-pipfile
RUN pip install git+https://github.com/PHT-Medic/train-container-library.git

COPY src /opt/train-router/src

CMD ["python", "-u", "/opt/train-router/src/TRConsumer.py"]
