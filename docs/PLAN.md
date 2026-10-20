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
| 6 | Inference gateway: scheduled GPU access, local-to-cloud routing, OS-held credentials per user/agent, usage ledger | requirements 2026-10-17 (phase6-inference-gateway.md); slice 1 vault + ledger done 2026-10-18 (phase6-slice1-vault.md); slice 2 gateway + scheduler + local Ollama done 2026-10-18 (phase6-slice2-gateway.md); slice 3 routing + cloud done 2026-10-18 (phase6-slice3-routing.md); slice 4 degradation, alerts, delegation, export done 2026-10-18 (phase6-slice4-operations.md); later: quality judge, multi-host |
| 7 | Components (snap-like selection, Route B native packages): maludb-api done 2026-10-17, Business OS kernel done 2026-10-18 (boot test PASS); applications next; ISO catalogue layers and maluctl selector (docs/components.md) | in progress |
| 8 | Agents as system entities: `maluctl agent create` (user, principal, identity, compartment, policy, token, hardened unit) | done 2026-10-18 (docs/agents.md); polkit and nspawn/bubblewrap sandboxes later |
| 9 | Editions, the Ubuntu Pro model: Community free, Professional per machine (esm, models, compliance, audit, backup, support), Enterprise per fleet (fleet, sso, scheduler); entitlements by token, services additive | requirements drafted 2026-10-18 (phase9-editions.md) |
| 10 | Public release of the free edition on maluos.com: maluos.com domains baked in (done), production key, R2 hosting, download page, source page, release | in progress 2026-10-19 (docs/release.md, docs/branding.md) |
| 11 | A MaluOS installer (text UI: disks, user, network, unpack the squashfs, seed first boot) replacing subiquity, the last Ubuntu-branded surface | proposed |
| 12 | The desktop variant: maluos-desktop (GNOME 50, no snaps, MaluOS identity), desktop rootfs, cloud image and ISO from the same scripts with `-p desktop`, profile-aware boot test (docs/phase12-desktop.md); the agent-aware session: session service, indicator, notifications; then desk enrolment | slice 1 built 2026-10-19; slice 2 (session) built 2026-10-19 |
| 13+ | Further agent-native features (journal to memory, quality judge) | |

### Phase 6+ candidates

- Agent identity as a system concept: done in Phase 8 (maluos-agent); polkit rules later.
- Sandboxed agent execution profiles: the maluos-agent@ unit's hardening and `--sandbox strict` today; nspawn, bubblewrap, Landlock later.
- MCP broker and mc2dbd as socket-activated system services; `maluctl` to enroll agents, grant scopes, inspect memory.
- journald/audit events ingested into memory as episodes.
- Secrets via systemd-creds: done in Phase 6 slice 1 (maluos-vault).
- Optional local inference packages wired to maludb_modeld: done in Phase 6 slice 2 (maluos-gateway drains the queue; Ollama installer).
- Desktop variant with an agent-aware session: Phase 12 (slice 1 done; the session is the next slice).

## Open items

- Public hosting for the repository: tooling ready (repo/publish-remote.sh, docs/release.md); DNS and the static host for apt.maluos.com are still to be provisioned.
- Production signing key custody: tooling and policy ready (repo/make-production-key.sh, keyring imports several keys, docs/release.md); the key itself is created by a person with the passphrase, primary stored offline.
- maludb-mc2dbd OS user / PG user mismatch: handled since Phase 4 (first boot creates the listener role named after the unit's user).
- Release cadence: decided, dated builds 26.04.YYYYMMDD on the Ubuntu point release (scripts/release.sh, release workflow, docs/release.md).
