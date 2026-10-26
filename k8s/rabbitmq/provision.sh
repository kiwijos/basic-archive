#!/bin/sh
# Runs inside the broker each time it starts, once the server is up. Every step is safe to repeat.
#
# 1. A broker from before slice 12 holds record.changed without single-active-consumer, which a queue cannot be
#    changed to: delete it once so the import re-creates it (make reindex repairs whatever it held).
# 2. Import the exchanges, queues and bindings.
# 3. One login per service, each allowed to do only what that service does. The passwords come from the
#    rabbitmq-users Secret, in this container's environment. Nothing connects as the broker's own administrator.
set -eu

if rabbitmqctl -q list_queues name arguments | grep '^record.changed[[:space:]]' | grep -qv single-active-consumer; then
  rabbitmqctl delete_queue record.changed
fi
rabbitmqctl import_definitions /etc/rabbitmq/definitions.json

login() { # login NAME PASSWORD CONFIGURE WRITE READ (the last three are patterns for the names it may use)
  # rabbitmqctl takes the password as an argument, so it is in this container's process list for the instant the
  # command runs, to processes in the broker's own container only. The check keeps a real failure of add_user visible.
  if rabbitmqctl -q list_users | cut -f1 | grep -qx "$1"; then
    rabbitmqctl -q change_password "$1" "$2"
  else
    rabbitmqctl -q add_user "$1" "$2"
  fi
  rabbitmqctl -q set_permissions -p / "$1" "$3" "$4" "$5"
}

# catalog-api only publishes events, through the one exchange.
login catalog-api "$CATALOG_API_PASSWORD" '^$' '^archive\.events$' '^$'
# The worker reads OCR jobs and publishes the next attempt of one that failed.
login transcribe-worker "$TRANSCRIBE_WORKER_PASSWORD" '^$' '^archive\.events$' '^ocr\.requested$'
# The indexer only reads changes.
login indexer "$INDEXER_PASSWORD" '^$' '^$' '^record\.changed$'
