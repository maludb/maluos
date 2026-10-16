# Phase 1: the MaluOS package repository

## What exists

| Piece | Where | Purpose |
|---|---|---|
| maluos-keyring | packages/maluos-keyring | Archive public key at /usr/share/keyrings/maluos-archive-keyring.gpg |
| maluos-archive | packages/maluos-archive | deb822 sources for MaluOS and PGDG; depends on postgresql-client-common for the PGDG key |
| maluos-base, maluos-server | packages/maluos-meta, generated from seeds/ | Metapackages |
| aptly repo `maluos-resolute` | ~/.aptly, published to ~/.aptly/public | Signed suite `resolute`, component `main`, Origin/Label MaluOS |
| bootstrap/ | ~/.aptly/public/bootstrap | keyring + archive .debs and install-maluos.sh for clean boxes |

The repo also carries the MaluDB engine packages built from maludb-core-26
(postgresql-18-maludb-core, maludb-mc2dbd). They are added as prebuilt .debs
by passing their paths to repo/publish.sh.

## Workflow

```
repo/init.sh                         # idempotent: key, ~/.aptly.conf, aptly repo
scripts/build-packages.sh            # regenerates meta control from seeds, builds, lintian
repo/publish.sh [extra.deb ...]      # add to aptly, sign + publish, stage bootstrap/
repo/serve.sh                        # http://127.0.0.1:8080 for local tests
sudo tests/chroot-install-test.sh    # acceptance test (below)
```

To add a package to a variant, edit seeds/<variant>.seed and bump
packages/maluos-meta/debian/changelog. To add a variant, add seeds/<name>.seed
and a line in packages/maluos-meta/debian/descriptions.

## Acceptance test

tests/chroot-install-test.sh builds a clean resolute rootfs with mmdebstrap
from the Ubuntu mirror, then runs scripts/install-maluos.sh inside it against
the locally served repository. It passes when maluos-server and its whole
dependency chain (PostgreSQL 18 from PGDG, the MaluDB extension and the MC2DB
listener from the MaluOS repo) are installed and the extension's shared object
is present. First run on 2026-10-16: PASS.

The test builds a variant of maluos-archive whose URI is the local server;
the published package points at the production URL from repo/config.env.

## Client bootstrap

On a stock Ubuntu 26.04 system:

```
curl -fsSL https://apt.maludb.org/maluos/bootstrap/install-maluos.sh | sudo bash
```

or, against a local server, `MALUOS_APT_URL=http://host:8080 sudo -E bash install-maluos.sh`.

## Caveats

- maluos-archive ships /etc/apt/sources.list.d/pgdg.sources, the same name
  the PGDG helper script writes, but without the Architectures line. A host
  that ran the script first gets a conffile prompt; accept the package
  version. This dev host is such a host.
- The signing key has no passphrase and lives in ~/.gnupg of the build user.
  Before public release, generate a production key kept offline or in an HSM,
  and ship both keys in maluos-keyring during the rollover.
- Hosting is not decided. The published tree is static files, so any of
  rsync to a web host, S3 + CloudFront, or GitHub Pages works.
- aptly publishes for amd64, arm64 and all; arm64 engine packages do not
  exist yet.
