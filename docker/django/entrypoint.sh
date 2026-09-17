#!/bin/sh
set -e

manage check --deploy
exec uvicorn clx.main:application --host 0.0.0.0 --port 8000
