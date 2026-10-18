# Phase 9: editions, the Ubuntu Pro model for MaluOS

Requirements and plan for MaluOS Community, Professional and Enterprise:
one operating system, entitlements attached to a machine with a token,
paid services enabled on top. Status: draft for review, 2026-10-18.

## 1. Purpose

MaluOS will be sold the way Ubuntu is: the whole operating system is free,
and a subscription attaches services to a machine or a fleet. Nothing in
the free edition is removed or crippled; what is paid is assurance over
time (maintenance), proof (compliance and audit), scale (fleet
management, more GPUs) and help (support). This keeps the developer path
that creates demand free, keeps one code base and one image, and makes the
commercial side a set of services with a clear contract rather than a
second product.

## 2. What already exists and is reused

| Existing | Role in the editions |
|---|---|
| Seeds and metapackages (maluos-server, maluos-api, ...) | an edition is a seed; images and boot tests cover it for free |
| Signed apt repository, aptly, publish-remote | the paid repositories are more aptly publishes behind authentication |
| The vault | holds the machine credential, the fleet enrolment key, and receives pushed secrets |
| The ledger | the audit record that Professional exports tamper-evidently and Enterprise aggregates |
| Policies, tiers, classes, budgets | what Enterprise manages centrally |
| First boot and maluctl | `maluctl pro` and `maluctl fleet` are plugins like `secret` and `gateway` |
| Alerts and hooks | the channel Enterprise forwards centrally |
| Release tooling (dated builds, signed checksums) | the maintenance channel is a longer-lived release line |

## 3. Terms

- **Edition**: Community, Professional, Enterprise. The installed OS is the
  same; the edition is the set of entitlements attached.
- **Subscription**: a commercial agreement; it issues **tokens**.
- **Token**: a string a person types once (`maluctl pro attach`); it is not
  the machine's credential.
- **Machine credential**: a keypair generated on the host at attach time,
  registered with the contracts service; it authenticates every later call
  and the paid repositories.
- **Entitlement**: a signed document listing the services a machine may
  enable, their parameters and expiry.
- **Service**: one enableable thing: a repository, a package set, a
  configuration, a remote endpoint (`esm`, `models`, `compliance`,
  `audit`, `fleet`, `sso`, `support`).
- **Contracts service**: the API that turns tokens into credentials and
  entitlements; the only writable commercial component.
- **Fleet**: the Enterprise management server and the hosts enrolled in it.

## 4. Goals and non-goals

Goals: one image and one code base for all editions; attach and detach
without reinstalling; a detached machine keeps working as Community; every
paid service is additive and reversible; entitlements verifiable offline
for a grace period; the paid repositories are ordinary apt for the client;
the commercial components are small enough to self-host for testing.

Non-goals for this phase: billing and payment (a later phase feeds the
contracts service); a web console (the CLI and the fleet API are the
interfaces); feature flags inside the free packages that check for a
subscription (there are none by design); desktop editions.

## 5. The edition matrix

| Service | Community | Professional (per machine) | Enterprise (per fleet) |
|---|---|---|---|
| The OS: engine, vault, gateway, agents, API, Business OS kernel | yes | yes | yes |
| Public repository, dated releases | yes | yes | yes |
| `esm`: maintenance channel for the MaluDB stack and its PostgreSQL combinations, 5 years from each release | | yes | yes |
| `models`: curated, tested model packs and tier ladders per GPU class, with measured prices and service times | | yes | yes |
| `compliance`: hardening profiles for agent hosts (systemd, apt, sshd, audit), a checker, a report | | yes | yes |
| `audit`: tamper-evident ledger exports (hash chain, signed), retention policy, shipping to a store | | yes | yes, central |
| `backup`: vault export to a key service or object store on a schedule | | yes | yes |
| `support`: issue tracker with a response time | | business hours | contracted |
| `fleet`: enrolment, central policies, tiers, secrets and alerts across hosts, aggregated usage | | | yes |
| `sso`: principals from an identity provider (OIDC, LDAP), group to scope mapping | | | yes |
| `scheduler`: multi-host GPU scheduling, a fleet-wide queue | | | yes |
| Free personal use | up to 3 machines on a personal token | | |

Rule for adding a service: if it makes an individual developer's agent
less capable, it is not a paid service.

## 6. Architecture

```
maluctl pro / maluctl fleet  (plugins on every host)
   │  HTTPS, machine credential
   ▼
contracts service  ──── issues ────▶  entitlement (signed JSON)
   │                                       │
   │ grants per-machine repository          ▼
   │ credentials                     host enables services:
   ▼                                  apt sources + auth, metapackages, config keys,
pro.maludb.org (aptly, authenticated)   units, timers
   suites: resolute-esm, resolute-models, resolute-compliance, resolute-enterprise

fleet server (Enterprise)  ◀──── hosts enrol with the machine credential
   policies, tiers, secrets (pushed as vault bundles), alerts, usage, SSO mapping
```

The contracts service and the fleet server are two small services under
the maludb organisation, self-hostable, with an API that the hand-run stub
implements first. Nothing on the host trusts them for anything but the
entitlement document and pushed configuration, both signed.

## 7. Functional requirements

### 7.1 Attach, entitlements, identity

- FR-1 `maluctl pro attach TOKEN` generates an Ed25519 machine keypair,
  stores the private key in the vault's `system` compartment, registers
  the public key and the host's facts (machine-id, release, edition
  wanted, hardware class) with the contracts service, and receives an
  entitlement document.
- FR-2 The entitlement document is signed by the contracts service key
  (shipped in maluos-keyring); the client verifies it, caches it under
  /var/lib/maluos/pro, and refreshes it on a timer (daily) and on demand.
- FR-3 Offline: a cached entitlement stays valid for its grace period
  (30 days past `refresh_by`); after that services are marked `expired`
  but nothing installed is removed.
- FR-4 `maluctl pro status` shows the edition, the services with their
  state (available, enabled, expired, not entitled), the expiry, the last
  refresh. `maluctl pro detach` disables services that depend on
  entitlement (repositories, fleet), keeps installed packages, and
  deletes the machine credential.
- FR-5 Personal tokens attach up to 3 machines; the contracts service
  refuses the fourth with a clear message.
- FR-6 The machine credential signs requests to the contracts and fleet
  services (HTTP signature with a timestamp); no shared secrets travel.
- FR-7 Attaching is a ledger event; so are enable, disable, refresh
  failures and detach.

### 7.2 Services on the host

- FR-8 `maluctl pro enable SERVICE` performs that service's enable steps
  idempotently and `disable` reverses them; services declare their steps
  in a manifest shipped by the package `maluos-pro` (sources, packages,
  config keys, units), not in code per service where avoidable.
- FR-9 Repository services write a deb822 source with `Signed-By` the
  MaluOS keyring and per-machine credentials in /etc/apt/auth.conf.d,
  then `apt-get update`; the credentials are the machine credential's
  derived repository token, rotated by the contracts service.
- FR-10 `esm`: the maintenance suite carries only packages that also
  exist in the free suite (same names, higher versions): security and
  compatibility fixes for the MaluDB stack and pinned PostgreSQL majors,
  for 5 years from each dated release line. A machine on `esm` receives
  them by ordinary apt upgrade.
- FR-11 `models`: packages `maluos-models-<class>` (per GPU class: 8 GB,
  16 GB, 24 GB, 48 GB, cpu) that register tiers, aliases, keep-warm lists,
  prices and measured service times for a tested model set, and pull the
  models through the gateway on enable.
- FR-12 `compliance`: a profile package (`maluos-compliance`) with the
  hardening settings for an agent host, a checker (`maluctl compliance
  check`) that reports pass or fail per control and writes the report to
  the ledger and to memory, and an apply mode with a diff.
- FR-13 `audit`: `maluctl audit export` writes the ledger for a period as
  a hash-chained, signed file (previous hash in every row, machine
  credential signs the file); `audit ship` sends it to a configured store
  (S3-compatible or the fleet server) on a timer; `audit verify` checks a
  file; retention of the live ledger becomes a policy with roll-ups.
- FR-14 `backup`: scheduled vault export (the slice 4 bundle) encrypted
  to a key held outside the host (an age or GPG public key, or the fleet
  server's key), shipped to the configured store; restore documented and
  tested.
- FR-15 `support`: `maluctl pro support bundle` collects versions, the
  done summary, unit states, the last journal lines of the MaluOS units,
  the gateway status and the alert list, with secrets redacted, into an
  archive the person sends with a ticket.

### 7.3 Enterprise: fleet

- FR-16 `maluctl fleet enroll` registers the host with the fleet server
  using the machine credential; the host's facts, components, backends,
  tiers and policies become visible there.
- FR-17 The fleet server pushes configuration as signed documents the host
  applies: gateway policies, tiers and aliases, classes, prices, alert
  settings, agent definitions; the host records what it applied in the
  ledger. Local changes to centrally managed objects are reported as
  drift, not silently overwritten.
- FR-18 Secrets distribution: the fleet server pushes vault bundles
  encrypted to the host's machine credential (the slice 4 import path);
  a secret may be scoped to hosts, groups or all; rotation is a push.
- FR-19 Alerts and usage flow up: the host's alert hook forwards to the
  fleet server; the host ships ledger roll-ups (not raw prompts) on a
  timer; the fleet server answers "what did principal X spend across the
  fleet this month" and "which hosts have the GPU down".
- FR-20 `sso`: the fleet server maps identity provider users and groups to
  principals and scopes; hosts create principals and Linux users on first
  login through the mapping (PAM and the first-boot principal creation
  already in place); the gateway's token issuance can be delegated to the
  identity provider.
- FR-21 `scheduler`: a fleet-wide view of expected waits per host and
  class; a host whose local wait exceeds the class threshold may route to
  a peer host's gateway before the cloud (a new rung kind,
  `peer_gateway`, authenticated with machine credentials), under the same
  sensitivity rules since peers are inside the fleet.
- FR-22 Host groups and roles on the fleet server: operators, auditors
  (read ledgers only), billing (counts only).

### 7.4 Repositories and packaging

- FR-23 Paid suites live on a separate host (`pro.maludb.org`) with
  per-machine HTTP credentials validated against the contracts service
  (web server auth request), published by aptly from the same build
  pipeline; `publish-remote` grows a target per suite.
- FR-24 Paid packages are additive: metapackages, profiles, model packs,
  the fleet agent. No free package ever depends on a paid one.
- FR-25 Editions are seeds: `pro.seed` (maluos-pro + the Professional
  metapackages) and `enterprise.seed`; the server image can carry them
  disabled, since enabling needs an entitlement anyway.
- FR-26 The contracts service and the fleet server are packaged
  (`maluos-contracts`, `maluos-fleet`) so an Enterprise customer can run
  them on their own network, and so CI can test the whole path.

## 8. Data model sketch

Host side (/var/lib/maluos/pro, plus the vault):

```
entitlement.json     signed: {machine_id, edition, services: {name: {state, params, until}}, issued, refresh_by, grace_until}
services.json        what is enabled locally and the steps applied
system/pro-machine-key   (vault) the machine's private key
```

Contracts service (PostgreSQL):

```
contract     (contract_id, kind {personal,professional,enterprise}, owner, seats, valid_until, created_at)
token        (token_id, contract_id, token_hash, kind, machines_max, revoked_at)
machine      (machine_id, contract_id, public_key, facts jsonb, attached_at, last_seen, detached_at)
entitlement  (machine_id, document jsonb, signature, issued_at, refresh_by)
repo_cred    (machine_id, suite, username, secret_hash, rotated_at)
```

Fleet server (PostgreSQL): hosts, groups, managed documents (policies,
tiers, agents, secrets bundles) with versions and signatures, applied
state per host, drift, usage roll-ups, alerts, identity mappings.

## 9. Non-functional requirements

- Security: the host never holds a long-lived shared secret; the machine
  key lives in the vault; entitlement and configuration documents are
  signed and verified before use; the paid repositories are signed with
  the same archive key as the free one; the fleet server cannot read raw
  prompts or secret values (bundles are encrypted to the host).
- Availability: hosts work without the contracts or fleet service being
  reachable, within the grace period; pushes resume where they stopped.
- Privacy: usage shipped to the fleet is roll-ups and metadata (tokens,
  cost, class, model); content never leaves the host unless the audit
  service is configured to ship full ledger rows, and even then prompts
  are not in the ledger.
- Compatibility: attach and detach keep working across dated releases;
  an entitlement document has a version and the client refuses unknown
  major versions.
- Operability: everything the services do is in the ledger and in
  `maluctl pro status`; a support bundle is one command.

## 10. Decisions proposed for review

| Decision | Proposed |
|---|---|
| What is paid | §5 as written: maintenance, model packs, compliance, audit, backup, support in Professional; fleet, SSO, multi-host scheduling in Enterprise. All agent-native capability stays free. |
| Free personal use | 3 machines on a personal token, no time limit, no support. |
| Maintenance length | 5 years from each dated release line for the MaluDB stack and its pinned PostgreSQL majors; the Ubuntu base keeps Ubuntu's own terms. |
| Licensing | free packages: current open licence; paid packages and the two services: commercial licence, source available to customers; the MaluOS trademark policy written in this phase. |
| Units of sale | Professional per machine per year; Enterprise per fleet (hosts, seats) per year. |
| Where the commercial code lives | separate repositories under the maludb organisation (maluos-pro, maluos-contracts, maluos-fleet); this repository stays entirely free. |

## 11. Delivery slices

1. **Entitlements**: maluos-pro package with `maluctl pro` (attach, status,
   refresh, detach, enable/disable of repository services), the contracts
   service as a self-hostable stub (tokens by hand, signed entitlements,
   repository credentials), the authenticated `pro.maludb.org` layout and
   the `esm` suite, the edition seeds. Boot test: attach to a stub in the
   test VM, enable `esm`, apt sees the suite, detach.
2. **Professional services**: `models` packs for two GPU classes,
   `compliance` profile and checker, `audit` export, ship and verify,
   `backup`, the support bundle.
3. **Fleet**: the fleet server, enrolment, pushed policies and tiers,
   secrets distribution, alerts and usage upstream, drift reporting, host
   groups and roles.
4. **Enterprise identity and scale**: `sso` mapping, `scheduler` with the
   peer-gateway rung.
5. **Commerce**: billing feeding the contracts service, self-service
   tokens, renewal and expiry flows.

## 12. Acceptance tests

- A Community machine is byte-for-byte the same image as a Professional
  one before attach; attach, enable `esm`, and `apt upgrade` installs a
  package version that exists only in the maintenance suite; detach keeps
  the package and removes the source and the credential.
- A personal token attaches three machines and refuses the fourth.
- A machine offline for 29 days keeps its services; on day 31 `status`
  shows them expired and nothing is uninstalled.
- A tampered entitlement document is refused and logged.
- The audit export verifies, and verification fails when any row is
  altered.
- A fleet policy pushed to a group changes the gateway's behaviour on
  every host in the group within the refresh interval, and a local edit
  shows as drift.
- A secret pushed by the fleet server is usable by the intended principal
  on the intended host and by nobody else; the fleet server cannot read
  it back.
- SSO: a user in group `research` logs in and gets principal and scopes
  from the mapping; removal from the group disables the principal.

## 13. Risks

- Scope creep in the paid tier erodes the free edition. Mitigation: the
  rule in §5 and a review of every new service against it.
- The contracts service becomes a single point of failure for customers.
  Mitigation: grace periods, offline validity, a self-hosted option.
- Repository authentication on a static host is awkward. Mitigation: a
  thin auth-request endpoint on the contracts service; the content itself
  stays static and cacheable.
- Fleet-managed secrets concentrate risk. Mitigation: bundles encrypted to
  the host, the fleet server holds only ciphertext, rotation is a push.
- Two more services to run (contracts, fleet). Mitigation: both packaged,
  both small, both testable in CI with the existing image pipeline.
