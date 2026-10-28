#!/bin/bash
# Install the default applications beside the kernel (Projects' K4, 2026-09-28; Help Desk added and the
# repositories named 2026-10-04): the tenant provisioning script's last step, and the command for a kernel
# that was provisioned before the defaults existed. Each application is installed by bin/app_install.php
# from its repository — HR, then Projects, then Help Desk, then Spaces (K21, 2026-10-05) — with every standing department granted its
# member role at write and its declared agents hired (the owner's rule for the defaults: hired on install,
# not merely proposed). Run as root on the kernel host.
#
#   sudo bin/install_default_applications.sh [<source>] [--by <super-admin email>] [--domain <domain>] [--scheme http|https]
#
# Every application of the OS lives under github.com/maludb as maludb-os-<catalog_key> (the kernel itself is
# maludb-os-core). <source> is a git URL prefix — by default https://github.com/maludb, so the defaults come
# straight from GitHub — or a directory holding the repositories as maludb-os-<key>/ or <key>/ (a server
# that keeps local clones, as this one does under /srv/apps). Every other option is passed to app_install.php
# as it is. An application already installed is reconciled, not reinstalled.
set -euo pipefail
K=$(cd "$(dirname "$0")/.." && pwd)
SRC=https://github.com/maludb
if [[ $# -gt 0 && "$1" != --* ]]; then SRC=$1; shift; fi
DEFAULTS=(hr projects helpdesk spaces)
for key in "${DEFAULTS[@]}"; do
    if [[ "$SRC" =~ ^(https?://|git@|ssh://) ]]; then
        repo="${SRC%/}/maludb-os-${key}.git"
    elif [[ -f "${SRC%/}/maludb-os-${key}/maludb-os.json" ]]; then
        repo="${SRC%/}/maludb-os-${key}"
    elif [[ -f "${SRC%/}/${key}/maludb-os.json" ]]; then
        repo="${SRC%/}/${key}"
    else
        echo "install_default_applications: no repository for ${key} under ${SRC} (looked for maludb-os-${key}/ and ${key}/) — skipped" >&2
        continue
    fi
    echo "== ${key} from ${repo}"
    php "$K/bin/app_install.php" apply "$repo" --hire-agents --grant-standing-departments "$@"
done
