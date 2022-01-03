#!/bin/bash
set -e

if [ "$1" = 'test' ]; then
  echo "Running tests..."
  pipenv install --dev --system --deploy --ignore-pipfile
  pip install -e /opt/router/
  coverage run -m pytest /opt/router/router
  exec coverage xml -o /opt/coverage/coverage.xml

fi
if [ "$1" = 'run' ]; then
    echo "Starting train router..."
    exec python /opt/router/TRConsumer.py
fi

exec "$@"