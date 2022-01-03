#!/bin/bash
set -e

if [ "$1" = 'test' ]; then
  echo "Running tests..."
  pipenv install --dev --system --deploy --ignore-pipfile
  pip install -e /opt/router/
  exec pytest /opt/router/router

fi
if [ "$1" = 'run' ]; then
    echo "Starting train router..."
    exec python /opt/router/TRConsumer.py
fi

exec "$@"