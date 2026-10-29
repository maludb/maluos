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

A third rule since 2026-10-27, the freshness guard: every artefact must
come from this tree. Release 26.04.20261027 shipped the ISOs of 10-24
(gateway 0.3.4) beside that day's cloud images because the script staged
whatever `build/` held. Now, for each profile, the image's manifest
(`build/image/maluos-P.manifest`) and the ISO's (`/casper/maluos-P.manifest`,
read with xorriso) must list every package this tree builds at the version
its `debian/changelog` declares, and both files must be newer than the last
commit that touched `packages/`, `seeds/`, `image/` or `iso/`. A stale
artefact stops the script, dry run included, with the package and the
versions named; `--stale-ok` releases it anyway for a knowing exception
(a hotfix of one profile, say) and prints the findings beside the release.

The passphrase prompt comes first, before staging. The script sets
`GPG_TTY`, signs a test line with the production key and lets gpg-agent
cache the passphrase (10 minutes by default) for the real signature a
few minutes later; files already staged under the day's name (same size,
newer than the build) are not copied again. Before 2026-10-23 the prompt
came after five minutes of staging, pinentry-curses drew it on the
release terminal while the maintainer was looking at another pane, and it
expired after its 60 s default: `gpg: signing failed: Timeout`.
`~/.gnupg/gpg-agent.conf` on the dev host now sets `pinentry-timeout 1800`.

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
- The public MaluApps catalogue (`docs/site/apps/catalog.json`): since
  Phase 12 slice 9 desks accept it only with `catalog.json.asc`, a
  detached signature by the release key (the archive signing key that
  maluos-keyring ships). `scripts/release.sh` signs and publishes both
  under `apps/` on the download bucket at every release;
  `scripts/publish-catalog.sh` does only that between releases (both ask
  for the production passphrase).
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
| 26.04.20261023 | 2026-10-23 | server, desktop | both image sets from 235c291 (sha256: server ISO 91345a…, server qcow2 91da5c…, desktop ISO 148219…, desktop qcow2 3f2edc…); tagged at b7902ba | Fourth desktop release. Phase 12 slice 6: desk enrolment (maluos-desk 0.1.1: `maluctl office enroll|status|heartbeat|leave`, the desk token in the vault, the office's model endpoint as a gateway rung, presence from the session, the office on the Desk page; maluos-desktop-session 0.4.0, maluos-agent 0.2.1, maluos-meta 0.2.4) and the kernel half of the same contract in the server images (maludb-os-core 2026.10.22maluos1: the migration, four endpoints, Settings → Desks, the presence sweep). Both images boot-tested on UEFI (TCG: desktop 186 checks, server 122 including the office half against the real kernel); both ISOs passed the apt replay check. Staging, hashing and uploads went through `scripts/gentle.py` after the dev VM was killed by its hypervisor during plain `cp`/`sha256sum` over the images. The first run failed at signing (the pinentry dialog expired unobserved after 60 s); `release.sh` now asks for the passphrase before staging. The download page lists both. apt.maluos.com republished the same night (Release dated 01:26 UTC) with the slice 6 set (maluos-desk 0.1.1, maluos-desktop-session 0.4.0, maluos-agent 0.2.1, the 0.2.4 metapackages, maludb-os-core 2026.10.22maluos1), the signed InRelease verified by `repo/publish-remote.sh`. |
| 26.04.20261025 | 2026-10-25 | server, desktop | both image sets from the slice 9 tree (built from 5511822, tag v26.04.20261025 at c74f16e; sha256: server ISO 1c2f43…, server qcow2 641f1d…, desktop ISO b3b722…, desktop qcow2 79102a…) | Phase 12 slice 9: grant requests decided with level, expiry and budget (Decide…, Choose… on the notification), a request's cause (the model call the gateway was refused a key for), agents' budget alerts to their owners by name, re-authentication through polkit before a reveal, a rotation and a backup (the vault asks; ledgered `reauth: polkit`), streamed answers in the Agents app and `maluctl agent send`, the office's agent page signed in with the desk token, the public MaluApps catalogue signed by the release key and verified on the desk (refused unsigned). Packages: maluos-vault 0.4.0, maluos-gateway 0.3.4, maluos-agent 0.4.0, maluos-agents 0.2.0, maluos-desk 0.4.0, maluos-desktop-session 0.7.0, maluos-meta 0.2.7. Boot tests: desktop UEFI 252 ok, server UEFI 140 ok; both ISOs passed the apt replay check. The release script now signs and publishes apps/catalog.json(.asc). |
| 26.04.20261027 | 2026-10-27 | server, desktop | cloud images from the shared-GPUs tree (tag v26.04.20261027 at ff4b02c; sha256: server qcow2 a7b949…, desktop qcow2 025dc3…); the ISOs were the 10-24 ISOs of 26.04.20261025 again (server 1c2f43…, desktop b3b722…), staged stale by the script: the freshness guard above came from this | Phase 13 shared GPUs (G1, G2, G5): the gateway as an inference node for other machines, the GPU reader and the sharing rule, the System Monitor's GPUs tab and the Network and Queue tabs, the first estate package (maluos-estate 0.1.1 against the mock office); gateway 0.4.1 in the cloud images while the ISOs still carried 0.3.4, and apt.maluos.com lagged at 0.3.4 until the next release. |
| 26.04.20261028 | 2026-10-28 | server, desktop | both image sets rebuilt 2026-10-27 20:22 after the freshness guard (built from fd4b169, tag v26.04.20261028 at a6b7f70; sha256: server ISO 29a97c…, server qcow2 732a47…, desktop ISO 12f394…, desktop qcow2 3942a7…) | The release fallout closed: fresh ISOs for both profiles, guard-clean, apt.maluos.com republished with the production key (gateway 0.4.3, estate 0.1.1, firstboot 0.1.11, vault 0.4.1, agent 0.4.0, maludb-os-core 2026.10.22maluos1). |
| 26.04.20261029 | 2026-10-29 | server, desktop | both image sets built 2026-10-29 11:42–12:25 from 91f301c, boot-tested twice (desktop UEFI, server UEFI; tag v26.04.20261029 at c827536; sha256: server ISO fd24f5…, server qcow2 d7f99b…, desktop ISO 0fb33d…, desktop qcow2 e7d2a1…) | Phase 13 slices 1, 1b and 2, the estate: a server joins an estate (`maluctl estate join`) and a desk enrols with its own signing key; the WireGuard overlay between the estate's machines; the agent directory and delegation (every agent's capabilities in the directory, tasks carried by signed envelopes and leased to the node's inbox, refusals with reasons, approvals and questions through the person's estate inbox, operator actions on remote nodes, the personal agent `maluctl agent create me --personal`); the kernel halves db/188 to db/190 (maludb-os-core 2026.10.28maluos2). Packages: maluos-estate 0.3.1, maluos-agent 0.5.2, maluos-agents 0.3.1, maluos-desk 0.6.0, maluos-desktop-session 0.10.0, maluos-gateway 0.5.2, maluos-vault 0.4.2, maluos-system-monitor 49.1+maluos.4, maluos-apple-t2-support 0.1.3. |
| 26.04.20261024 | 2026-10-24 | server, desktop | both image sets from the slice 8 tree plus maluos-desktop-session 0.6.1 (commit 27eb819, tag v26.04.20261024; sha256: server ISO 4da6b3…, server qcow2 4af130…, desktop ISO 1a215c…, desktop qcow2 ca9feb…) | Fifth desktop release, two slices in one. Phase 12 slice 7: the power defaults (no screen blank, no automatic suspend, maluos-desktop-branding 0.4.2), the Upgrade Manager (`maluctl update auto`, polkit action com.maluos.admin, maluos-firstboot 0.1.8), the Tools Installer (maluos-tools 0.1.0: Chrome, VS Code, Claude Code, Codex, Ollama), MaluApps from the office's catalogue and the public one (maluos-desk 0.2.0, download.maluos.com/apps/catalog.json), the Credential Manager, five windows in maluos-desktop-session 0.5.0. Phase 12 slice 8: the Agents app (maluos-agents 0.1.0, a WebKitGTK window over an HTML/JS UI: Talk, Control, Policy, Memory, Activity for local and office agents), the agent task interface (maluos-agent 0.3.0: maluos_agent_tasks on the unit's socket, `maluctl agent card|send|tasks`), the office's agent directory (maluos-desk 0.3.0: `maluctl office agents`, `office agent ID send|activity`), the agent icons in the grid's Agents folder and ~/Desktop/Agents kept by the session (maluos-desktop-session 0.6.0; 0.6.1 re-reads the MaluApps catalogue after each heartbeat). Servers gain maluos-firstboot 0.1.8 and maluos-agent 0.3.0. Boot tests: desktop UEFI 230 ok (slice 8 chain) and 231 ok with 0.6.1 (14:31 UTC), server UEFI 138 ok, server BIOS in CI; both ISOs passed the apt replay check. The dev VM was OOM-killed by its Proxmox host during slice 7 (host out of memory); it now runs with a 16 GB cap and an 8 GB balloon floor and the chains throttle their copies. Not possible on 26.04: agent icons on the desktop background (no desktop-icons extension in the archive). |
