# MaluOS

MaluOS is a Linux distribution derived from Ubuntu 26.04 LTS (resolute),
designed for both humans and AI agents and centred on the MaluDB memory
database.

This repository holds the distribution layer: the signed APT repository,
metapackages and seeds, branding, installer configuration, ISO build
pipeline and first-boot provisioning. The MaluDB engine itself lives in
[maludb/maludb-core-26](https://github.com/maludb/maludb-core-26).

See [docs/PLAN.md](docs/PLAN.md) for the phased plan and
[docs/phase1-repository.md](docs/phase1-repository.md) for how the package
repository works.

## Layout

```
packages/      source packages owned by MaluOS (keyring, archive, metapackages)
seeds/         package lists per variant; metapackage Depends are generated from these
repo/          aptly configuration and publish scripts
scripts/       build helpers and the client bootstrap installer
tests/         install tests (clean mmdebstrap chroot)
ci/            GitHub Actions
autoinstall/   subiquity autoinstall templates             (Phase 2+)
firstboot/     first-boot provisioning                      (Phase 4)
image/         rootfs + cloud image builders from the seeds (Phase 3)
iso/           ISO build: Ubuntu live installer + MaluOS rootfs (Phase 2/3)
docs/          plan and design notes
```

## Quick start (maintainer)

```
repo/init.sh            # one-time: signing key + aptly repo
scripts/build-packages.sh
repo/publish.sh ~/*.deb # publish built packages plus any extra .debs
repo/serve.sh           # serve the repo on http://127.0.0.1:8080
sudo tests/chroot-install-test.sh
```

## Long builds

Rootfs, image and VM tests take minutes to hours. Run them as transient
systemd units so they survive a dropped SSH or Claude Code session:

```
scripts/run-detached.sh rootfs sudo image/build-rootfs.sh
scripts/run-detached.sh qcow2  sudo image/build-qcow2.sh
scripts/run-detached.sh iso    iso/build-iso.sh
scripts/run-detached.sh test-qcow2 tests/qcow2-boot-test.sh
scripts/jobs.sh                 # what is running; scripts/jobs.sh <name> for status + log tail
```

Logs land in build/logs/<name>.log. Run interactive sessions themselves
inside tmux (`tmux new -s maluos`, reattach with `tmux attach -t maluos`).

## Quick start (client)

```
curl -fsSL https://apt.maludb.org/maluos/bootstrap/install-maluos.sh | sudo bash
```
