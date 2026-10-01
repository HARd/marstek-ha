#!/bin/sh
# Everything that runs without Home Assistant installed. Catches the class of bug
# that only shows up when a user presses a button: missing imports, undefined
# names, dead references.
set -e
ruff check --select F custom_components/
python3 test_api_udp.py
python3 test_cloud.py
