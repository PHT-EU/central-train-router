FROM python:3.8-buster

COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt


COPY src /opt/train-router/src

CMD ["python", "-u", "/opt/train-router/src/TRConsumer.py"]


