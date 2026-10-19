# Releases, keys and hosting

## Cadence

A MaluOS release is a dated build on top of the Ubuntu point release it
derives from: `26.04.YYYYMMDD` (file `VERSION`, tag `vVERSION`). Packages
keep their own Debian versions and flow through the apt repository
continuously; a release is the moment an ISO and a cloud image are built
from a tagged tree, boot-tested, named, checksummed, signed and published.

- Routine: a release whenever a phase or a meaningful fix lands and CI is
  green, at least monthly while the project is moving.
- Rebase: when Ubuntu ships a point release (26.04.2 ...), update the base
  ISO in iso/ and CI, rebuild, release.
- Hotfix: a package fix is just a package publish; it reaches installed
  systems through apt. A new release only when the install media must
  change.

`scripts/release.sh` does the mechanics: checks a clean main, names the
artefacts, writes SHA256SUMS and a clearsigned SHA256SUMS.gpg, generates
RELEASE-NOTES.md from the manifest and the git log, commits VERSION, tags,
pushes, creates the GitHub Release with the cloud image and checksums, and
pushes the ISO to the download host when MALUOS_DOWNLOAD_RSYNC is set (the
ISO is too large for a GitHub release asset). The `release` workflow then
rebuilds the cloud image from the tag in CI, boot-tests it, and attaches
that independently built copy to the same release.

## Signing keys

Two keys, two roles:

| Key | Where | Signs |
|---|---|---|
| Development key (`MaluOS Archive Automatic Signing Key`, no passphrase) | the maintainer's keyring on the build host | the local repository used for image builds and tests |
| Production key (`MaluOS Archive Signing Key (YEAR)`, passphrase, Ed25519, 2-year signing subkey) | signing subkey on the publishing host, primary secret key offline | the public repository and release checksums |

`repo/make-production-key.sh YEAR` creates the production key and exports
its public half into packages/maluos-keyring/keys/. The keyring package
imports every key there, so clients trust both during a transition.

Custody rules:

1. The primary secret key is exported once, stored offline (a USB key in a
   safe, or the password manager's file vault) and removed from the host;
   only the signing subkey remains. Losing the primary means a new key and
   a keyring update; losing the subkey means revoking it with the primary.
2. The passphrase lives in the password manager, never in a file on the
   host; gpg-agent asks for it once per publishing session.
3. Rotation (every two years, or on any suspicion): make the new key, ship
   a maluos-keyring update that carries both public keys signed by the old
   key, switch `MALUOS_SIGNING_UID`, and after one release remove the old
   public key from the package.
4. The development key never signs anything that leaves the LAN.

Publish with the production key:

```
MALUOS_SIGNING_UID="MaluOS Archive Signing Key (2026) <apt@maluos.com>" repo/publish.sh
MALUOS_REMOTE_RSYNC=deploy@apt.maluos.com:/srv/apt repo/publish-remote.sh
```

Production key in use since 2026-10-19:

```
pub   ed25519 2026-10-19 [C] [expires: 2031-10-18]
      6387 5A4A 5397 B902 E9C5  CFF8 731A DA39 4135 B9FF
uid   MaluOS Archive Signing Key (2026) <apt@maluos.com>
sub   ed25519 2026-10-19 [S] [expires: 2028-10-18]
```

This fingerprint belongs on the download page next to the verification
commands.

## Hosting

The repository is static files: `dists/` (signed indexes), `pool/`
(packages) and `bootstrap/` (keyring, archive package, installer script).
Any HTTPS static host works; `repo/publish-remote.sh` mirrors the published
tree with rsync or to S3-compatible storage, pool before indexes so a
client never sees an index naming a missing file, then verifies the remote
InRelease signature.

Recommended shape: `apt.maluos.com` as a static site (nginx or object
storage behind a CDN) holding the repository under `/maluos`, matching the
URL baked into maluos-archive; `download.maluos.com/VERSION/` for
ISOs and cloud images with SHA256SUMS and SHA256SUMS.gpg beside them. Both
are reads only; nothing on the public host can sign.

Until the public host exists, installs outside the LAN need the ISO (it
carries the pool) and the maluos-archive sources stay disabled, as they
are today.

## What is still manual

- Creating the production key and storing the primary offline (a person
  with the passphrase must do it).
- DNS and the static host for apt.maluos.com and download.maluos.com.
- The first keyring publish signed by the development key, which is how
  existing installs learn the production key.
