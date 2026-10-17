# MaluOS project plan

MaluOS is an Ubuntu 26.04 LTS derivative for humans and AI agents, centred on
the MaluDB memory database. The engine lives in maludb/maludb-core-26; this
repository is the distribution layer.

## Framing decisions

- **Derivative, not a true fork.** Packages come from the Ubuntu archive plus
  PGDG; MaluOS adds a signed repository, metapackages, branding, defaults,
  installer configuration and first-boot provisioning (the Pop!_OS / Mint model).
- **Server first, desktop later.** The memory host is headless; the desktop
  variant waits until the server variant is stable.
- **Trademark.** No "Ubuntu" in product name or branding; rebrand os-release,
  grub, motd and plymouth before any public ISO.
- **Architectures.** amd64 first; arm64 once the repo builds both.
- **Package hosting.** Self-hosted aptly repository, signed with the MaluOS
  archive key. PGDG is referenced as a second source, not mirrored (revisit for
  offline ISO installs in Phase 3).
- **Kernel and Secure Boot.** Use Ubuntu's signed kernel and shim unchanged.

## Phases

| Phase | Goal | Status |
|---|---|---|
| 0 | Repo layout, decisions | done 2026-10-16 |
| 1 | Signed package repository; one command installs the MaluDB stack on clean 26.04 | done 2026-10-16 (see phase1-repository.md) |
| 2 | First bootable ISO by remastering Ubuntu Server 26.04.1 with autoinstall + MaluOS pool + grub branding | built 2026-10-16 (see phase2-iso.md) |
| 3 | Own rootfs from seeds (mmdebstrap) as ISO install source + qcow2 cloud image; branding package; offline install | rootfs + qcow2 + ISO built 2026-10-17; qcow2 boot test PASS (see phase3-images.md) |
| 4 | First boot: maludb database, tenant, admin principal, listener role + token, operator logins; configured by /etc/maluos/firstboot.yaml (cloud-init writable); maluctl | done 2026-10-17, boot test PASS (see phase4-firstboot.md) |
| 5 | CI: packages on every push/PR; rootfs + qcow2 built in a container and boot-tested on BIOS and UEFI under KVM on GitHub runners; ISO on demand | done 2026-10-17, both workflows green |
| 6 | Inference gateway: scheduled GPU access, local-to-cloud routing, OS-held credentials per user/agent, usage ledger | requirements drafted 2026-10-17 (phase6-inference-gateway.md) |
| 7 | Components (snap-like selection, Route B native packages): maludb-api done 2026-10-17; Business OS kernel + applications next; ISO catalogue layers and maluctl selector (docs/components.md) | in progress |
| 8+ | Further agent-native features (sandboxing, journal to memory) and the desktop variant (after Phase 6 slices 1-2) | |

### Phase 6+ candidates

- Agent identity as a system concept: Unix user + maludb principal + polkit rules + scope grants.
- Sandboxed agent execution profiles (systemd-nspawn, bubblewrap, Landlock) shipped as units.
- MCP broker and mc2dbd as socket-activated system services; `maluctl` to enroll agents, grant scopes, inspect memory.
- journald/audit events ingested into memory as episodes.
- Secrets via systemd-creds.
- Optional local inference packages wired to maludb_modeld.
- Desktop variant with an agent-aware session.

## Open items

- Public hosting for the repository (apt.maludb.org is the placeholder baked into maluos-archive).
- Production signing key custody: the Phase 1 key is an unprotected dev key in the maintainer's GnuPG keyring.
- Fix the maludb-mc2dbd OS user / PG user mismatch (maludb-core-26 PR #1) in Phase 4, where the OS owns provisioning.
- Release cadence: track Ubuntu point releases or dated MaluOS builds.
