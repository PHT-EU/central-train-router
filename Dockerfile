FROM ubuntu
MAINTAINER michael.graf@uni-tuebingen.de
# update python version and replace python with python 3
RUN apt -y update && apt-get -y install software-properties-common
RUN add-apt-repository ppa:deadsnakes/ppa && apt -y update && apt -y install git
RUN apt-get install -y python3.8 && apt install python-is-python3 && apt install -y python3-pip

# install packages for train router
COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt


COPY src /opt/train-router/src

CMD ["python", "-u", "/opt/train-router/src/TRConsumer.py"]
