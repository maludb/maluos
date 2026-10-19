#!/bin/bash
set -euo pipefail
cd /home/maludb/maluos
echo "== rootfs $(date -u +%T)"; image/build-rootfs.sh
echo "== qcow2 $(date -u +%T)"; image/build-qcow2.sh
echo "== iso $(date -u +%T)"; iso/build-iso.sh
echo "== done $(date -u +%T)"
