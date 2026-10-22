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

Two rules the script enforces since 2026-10-22. The version is the UTC
date, so there is one release per day: if the day's tag exists the script
stops, and `--resume` is only for finishing an interrupted upload of the
same files. And the copying and hashing of the 13 GB of images go through
`scripts/gentle.py`, which releases each chunk from the page cache and
caps the rate at 100 MB/s, with the cache dropped every 15 s during the
uploads: the dev VM is a 14 GB guest that its hypervisor killed four times
when plain `cp` and `sha256sum` over the images filled the guest's cache
(docs/phase12-desktop.md, slice 6 status). Run the script in tmux.

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

Two published trees of the same repository, so nothing unattended ever
needs the production passphrase:

| Tree | Signed by | Used by |
|---|---|---|
| `~/.aptly/public/dists,pool` | development key | image builds, local tests, CI |
| `~/.aptly/public/public/dists,pool` | production key | `repo/publish-remote.sh`, which refuses any other signature, and so apt.maluos.com |

```
repo/publish.sh --public                      # asks for the production passphrase once per session
MALUOS_REMOTE_RSYNC=deploy@apt.maluos.com:/srv/apt repo/publish-remote.sh
MALUOS_REMOTE_S3=s3://maluos-apt MALUOS_S3_ENDPOINT=https://<account>.r2.cloudflarestorage.com repo/publish-remote.sh
```

The bootstrap keyring beside each tree carries both public keys, and the
maluos-keyring package ships both, so a client trusts either signature.
`scripts/release.sh` clearsigns SHA256SUMS with the production key.

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

### Setting up Cloudflare R2 (step by step)

Prerequisite: the maluos.com zone must be on Cloudflare's nameservers, since
R2 custom domains attach only to zones Cloudflare serves. If the DNS is
elsewhere, move it first (Cloudflare dashboard → Add a site → change the
nameservers at the registrar; existing records are imported).

1. **Buckets.** Dashboard → R2 Object Storage → Create bucket, twice:
   `maluos-apt` and `maluos-download`. Location: automatic. Leave public
   access off; the custom domain provides it.
2. **Custom domains.** For each bucket: Settings → Custom Domains →
   Connect Domain → `apt.maluos.com` for maluos-apt and
   `download.maluos.com` for maluos-download. Cloudflare creates the DNS
   record and the certificate; the status goes to Active within minutes.
3. **API token for uploads.** R2 → Manage R2 API Tokens → Create API token:
   name `maluos-publisher`, permission Object Read & Write, scope: the two
   buckets, TTL as you prefer. Copy the three values shown once: Access Key
   ID, Secret Access Key, and the endpoint
   `https://<account id>.r2.cloudflarestorage.com`.
4. **The aws CLI on the build host.** `sudo apt-get install awscli`, then
   create `~/.aws/credentials` with mode 0600:

   ```
   [maluos]
   aws_access_key_id = <Access Key ID>
   aws_secret_access_key = <Secret Access Key>
   ```

   and `~/.aws/config` with `[profile maluos]` and `region = auto`.
5. **Environment for the scripts** (put it in `~/.config/maluos/publish.env`
   and `source` it before publishing; never commit it):

   ```
   export AWS_PROFILE=maluos
   export MALUOS_S3_ENDPOINT=https://<account id>.r2.cloudflarestorage.com
   export MALUOS_REMOTE_S3=s3://maluos-apt
   export MALUOS_DOWNLOAD_S3=s3://maluos-download
   ```

6. **Test the credentials:** `aws --endpoint-url "$MALUOS_S3_ENDPOINT" s3 ls`
   lists the two buckets.
7. **First publish of the repository:** `repo/publish.sh --public` (the
   production passphrase), then `repo/publish-remote.sh`. It verifies the
   tree's signature, syncs pool then indexes, and fetches
   `https://apt.maluos.com/dists/resolute/InRelease` back to verify it.
8. **First release:** `scripts/release.sh` builds the dated release, tags,
   creates the GitHub Release with the cloud image, and syncs the ISO,
   image, SHA256SUMS and SHA256SUMS.gpg to
   `https://download.maluos.com/<version>/`, updating `LATEST`.
9. **Cache rules (optional, recommended):** in the zone's Caching → Cache
   Rules, cache everything under `download.maluos.com/*` for a day and
   `apt.maluos.com/pool/*` for a week; leave `apt.maluos.com/dists/*` at
   the 5 minute max-age the sync sets, so index updates propagate.

Costs: storage at R2's per-gigabyte rate (a release is about 6.5 GB),
no egress charges, negligible operation charges.

Until the public host exists, installs outside the LAN need the ISO (it
carries the pool) and the maluos-archive sources stay disabled, as they
are today.

## What is still manual

- Moving the primary secret key offline (custody step 2); the signing
  subkey stays on the build host. Done so far: key created 2026-10-19,
  keyring 0.2.1 carries it, apt.maluos.com and every release are signed
  with it.
- Running `repo/publish.sh --public`, `repo/publish-remote.sh` and
  `scripts/release.sh`: each asks for the production passphrase.
- Publishing the download page: `docs/site/download.md` (source) and
  `docs/site/download.html` (self-contained page) carry the links,
  fingerprint, verify commands, requirements and install guide. The page
  is published on the download bucket as `download.html` and `index.html`
  (https://download.maluos.com/download.html), after each release:
  ```sh
  source ~/.config/maluos/publish.env
  for k in index.html download.html; do
    aws --endpoint-url "$MALUOS_S3_ENDPOINT" s3 cp docs/site/download.html "$MALUOS_DOWNLOAD_S3/$k" \
      --content-type "text/html; charset=utf-8" --cache-control "max-age=300"
  done
  ```
  R2 custom domains serve objects by key only, so the bare
  `https://download.maluos.com/` is a 404 until a Cloudflare transform rule
  rewrites the path `/` to `/index.html` (dashboard: Rules, Transform
  Rules, Rewrite URL). The maluos.com landing page should link to the
  page and to the release files rather than to `/downloads/*.iso`.

## Releases so far

| Release | Date | Profiles | Built from | Notes |
|---|---|---|---|---|
| 26.04.20261019 | 2026-10-19 | server | bfa13ad (images), tagged at fe0476e | First public release. apt.maluos.com and download.maluos.com on Cloudflare R2; keyring 0.2.1; `--profiles=server` kept the unproven desktop pair out. |
| 26.04.20261020 | 2026-10-20 | server, desktop | server images unchanged from 26.04.20261019 (bfa13ad, same checksums); desktop images from 1457c2a; tagged at dbb0896 | First desktop release (Phase 12 slices 1 and 2: GNOME 50, no snaps, the agent-aware session; maluos-gateway 0.3.3, maluos-desktop-session 0.1.1). Desktop boot-tested on BIOS (KVM, CI run 39451539187); the ISO passed the apt replay check; and UEFI (TCG, 124 checks, finished after the release with the same checksums). The download page lists both. Known issue: the desktop ISO crashes in the installer with the default LVM layout (no lvm2 in the image or the ISO pool); untick "Set up this disk as an LVM group" on the Storage screen, or use the next release (fix: storage tools in the desktop profile, docs/phase12-desktop.md). |
| 26.04.20261021 | 2026-10-21 | server, desktop | server images unchanged from 26.04.20261019 (same checksums); desktop images from 8d1e069 (sha256 of the desktop ISO 75b0f1…); tagged at b9da733 | Second desktop release (Phase 12 slices 3 and 4: agent ownership, vault grant requests answered from the notification, the MaluOS Desk window, the MaluOS logo on wallpaper, greeter, icon and splash; maluos-vault 0.3.0, maluos-agent 0.2.0, maluos-desktop-session 0.2.0, maluos-branding 0.4.0). Fixes the 26.04.20261020 installer crash with the default LVM layout (storage tools in the desktop profile; `tests/iso-apt-check.sh` replays curtin's installs offline). Desktop boot-tested on UEFI (TCG, 139 checks); the ISO installed on a laptop and on Proxmox. The server image is still the 26.04.20261019 build, so it carries maluos-gateway 0.3.0, maluos-vault 0.2.0 and maluos-agent 0.1.0; the desktop carries the newer ones. The download page lists both. apt.maluos.com was published the same evening with the full dev set (maluos-gateway 0.3.3, maluos-vault 0.3.0, maluos-agent 0.2.0, maluos-desktop-session 0.2.0, the 0.4.0 branding, the 0.2.2 metapackages), verified with an `apt-get update` against the archive keyring; before that it had served the 2026-10-19 index with no desktop packages at all. |
| 26.04.20261022 | 2026-10-22 | server, desktop | both image sets from f6b6654 (sha256: server ISO a6ec62…, server qcow2 884fd4…, desktop ISO 8aef27…, desktop qcow2 4bdb1f…); tagged at d9f34ae | Third desktop release and the first with fresh server images since 26.04.20261019 (the server now carries maluos-gateway 0.3.3, maluos-vault 0.3.0, maluos-agent 0.2.0). Phase 12 slice 5: installed systems now actually receive updates (unattended-upgrades is a hard dependency and apt.maluos.com stays enabled after install; earlier releases never installed it and left the MaluOS source disabled), Firefox from packages.mozilla.org (maluos-archive-mozilla 0.3.0, Ubuntu's snap shim pinned out), GNOME Software with the deb plugin only, `maluctl update` and the session's update notifications and Desk page (maluos-desktop-session 0.3.1, maluos-firstboot 0.1.7, maluos-branding 0.4.1, maluos-meta 0.2.3). Both images boot-tested on UEFI (TCG: desktop 159 checks, server 114); both ISOs passed the apt replay check including `apt-get update` with the network sources unreachable. The download page lists both. apt.maluos.com republished the same afternoon (Release dated 15:27 UTC) with the full slice 5 set, verified with an `apt-get update` against the 2026 archive key. |
