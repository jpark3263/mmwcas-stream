#!/bin/sh
# scp to or from the TDA2 with the same options as tda2_ssh.sh; write the board side as tda2:<path>.
ROOT=$(cd "$(dirname "$0")/.." && pwd) || exit 1
IP=${TDA_IP:-$(python "$ROOT/tools/cfg.py" tda.ip)}
args=""
for a in "$@"; do
  case "$a" in tda2:*) a="root@$IP:${a#tda2:}" ;; esac
  args="$args \"$a\""
done
eval exec scp -O -q -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
  -o HostKeyAlgorithms=+ssh-rsa,ssh-dss -o PubkeyAcceptedAlgorithms=+ssh-rsa \
  -o KexAlgorithms=+diffie-hellman-group1-sha1,diffie-hellman-group14-sha1 $args
