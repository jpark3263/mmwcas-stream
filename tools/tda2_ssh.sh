#!/bin/sh
# Runs a command on the TDA2 over ssh (root, no password, legacy key algorithms for the board's old dropbear); the address comes from config.toml.
ROOT=$(cd "$(dirname "$0")/.." && pwd) || exit 1
IP=${TDA_IP:-$(python "$ROOT/tools/cfg.py" tda.ip)}
exec ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=5 \
  -o HostKeyAlgorithms=+ssh-rsa,ssh-dss -o PubkeyAcceptedAlgorithms=+ssh-rsa \
  -o KexAlgorithms=+diffie-hellman-group1-sha1,diffie-hellman-group14-sha1 \
  "root@$IP" "$@"
