#!/bin/bash -e

IMAGE="smtc_web"
DIR=$(dirname $(readlink -f "$0"))

cp -f "$DIR/../script/db_hint.py" "$DIR/../script/"/dsl_*.py "$DIR"
. "$DIR/../script/build.sh"
