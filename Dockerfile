FROM ubuntu
MAINTAINER michael.graf@uni-tuebingen.de
# update python version and replace python with python 3
RUN apt -y update && apt-get -y install software-properties-common && \
    add-apt-repository ppa:deadsnakes/ppa && apt -y update && apt -y install git && \
    apt-get install -y python3.9 && apt install python-is-python3 && apt install -y python3-pip && \
    rm -rf /var/lib/apt/lists && \
    pip install pipenv==2021.5.29 && \
    rm -rf /var/lib/apt/lists

WORKDIR /opt/router/

COPY Pipfile /opt/router/Pipfile
COPY Pipfile.lock /opt/router/Pipfile.lock

RUN pipenv install --system --deploy --ignore-pipfile

COPY . /opt/router

COPY ./entrypoint.sh /
ENTRYPOINT ["/entrypoint.sh"]
CMD ["test"]
