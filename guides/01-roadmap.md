# The end-to-end test: roadmap

One pass across hardware and applications: an office VM on Proxmox
running the Business OS kernel and its applications, a bare-metal GPU
server sharing inference, the two joined as one estate, and physical
desks (two laptops, then two Intel Mac minis) enrolled with the office.
Each stage has an exit criterion that a later stage depends on, so the
order is fixed. Status words: `planned`, `running`, `done`, `blocked`.

Started 2026-11-05 on MaluOS 26.04.20261102; from 2026-11-06 the servers
run the 26.04.20261106 packages and the desks install from that release's
ISOs (`https://download.maluos.com/26.04.20261106/`).

This is the historical test log. New installation procedures now use
[release 26.04.20261109](02-current-release.md), including office-setup
0.1.0. No stage below is marked newly completed by this documentation
refresh. The 26.04.20261106 release reused older ISO artifacts; the release
baseline explains why image and installed-package versions both matter.

## The machines

| Name | What | Where | Image | Hostname |
|---|---|---|---|---|
| office | the coordinator: the kernel, the estate's hub, the applications | a VM on a Proxmox host | maluos-server ISO | `office` |
| gpu-1 | the inference node: NVIDIA GPU, Ollama behind the gateway | bare metal in the office (the GPU dev host of 2026-11-04) | already installed, maluos-server | as installed |
| proxy | the existing nginx reverse proxy, TLS for every name | existing | unchanged | existing |
| desk-1, desk-2 | laptops | physical | maluos-desktop ISO | the person's choice |
| desk-3, desk-4 | Intel Mac minis | physical | maluos-desktop ISO (`maluos-apple-t2` added by the installer on a 2018 model) | the person's choice |

## Stages

| # | Stage | Document | Exit criterion | Depends on | Status |
|---|---|---|---|---|---|
| 0 | Prerequisites: the domain's names on the LAN DNS and the proxy, the ISOs downloaded and verified, the install plans written with real values, a place to serve a plan over HTTP | [30-reverse-proxy.md](30-reverse-proxy.md), [plans/](plans/) | `app.$DOMAIN`, `os.$DOMAIN`, the bare name and the five application names resolve from a desk to the proxy; the proxy answers 502 for each (nothing behind it yet); both ISOs' SHA256 match | nothing | DNS, proxy and TLS done 2026-11-05 (nine names, each with its certificate); the ISO, the plan's password hash and the DHCP reservation remain |
| 1 | The office: MaluOS server on Proxmox from the ISO, the kernel provisioned for `$DOMAIN` behind the proxy, the super-admin signed in | [Install](10-office-on-proxmox.md) → [first login / SSH](10-office-first-login-and-ssh.md) → [Business OS configuration](10-office-configuration.md) | `https://app.$DOMAIN` shows the launcher after sign-in; `https://os.$DOMAIN` opens for the super-admin; `maluctl status` lists every component ok | 0 | done 2026-11-05: screens install, kernel re-provisioned for tipdesk.org, 9 units active, the super-admin signed in at https://app.tipdesk.org through the proxy |
| 2 | The applications: HR, Projects, Help Desk, Spaces, DocCloud installed beside the kernel, their names on the proxy, each reachable from the launcher | [12-applications.md](12-applications.md) | `app_install.php plan` reads all done for each; `/launch/<id>` of each lands signed in; a document uploaded to DocCloud is searchable | 1 | done 2026-11-05: HR, Projects, Help Desk, Spaces and DocCloud active and up in the kernel, each healthy through the proxy, each opened signed in from the launcher; a ticket, a post and a DocCloud upload with search all worked. Eight findings in the log, six fixed by pull requests |
| 3 | The GPU server: brought to the current release, the driver and `nvidia-smi` live in `maluctl gpu status`, Ollama with one model behind the gateway, sharing on, the unwanted kernel off | [11-gpu-server.md](11-gpu-server.md) | `maluctl gateway chat "Say hello" --model qwen3:8b` answers on the box; `maluctl gateway share status` says on, contribution always | nothing (can run beside 1 and 2) | done 2026-11-05: RTX 3060 live in `maluctl gpu status` (driver 580.178.04 from `maluos-nvidia` after a reboot), Ollama 0.40.6 with qwen3:8b healthy behind the gateway, share on with contribution always, the kernel's units off; exposed on the LAN at 10.1.10.113:11435 from the dev work |
| 4 | The estate: the office joins its own estate as the hub, the GPU server joins as an inference node, the overlay is up, the office lists the node and its models | [13-estate.md](13-estate.md) | Settings → Estate at the office lists `office` and `gpu-1` online; `ping office.internal` answers from gpu-1; Shared inference lists gpu-1's models | 1, 3 | done 2026-11-07 (release 26.04.20261106): the office is the hub at vpn.tipdesk.org:51820 through Nginx Proxy Manager's UDP stream; gpu-1 (node 4) and gpu-2 (node 3) joined as spokes from their own networks, `ping office.internal` 27 ms; the office's chat with --prefer estate served by gpu-1; gpu-2's listener on the overlay pending |
| 5 | The desks: laptop 1 enrolled at install, laptop 2 enrolled after install, the Mac minis; each sees the office's applications and agents, each runs inference on gpu-1 over the overlay | [14-desks.md](14-desks.md) | on each desk: `maluctl office status` enrolled; `maluctl gateway chat … --prefer estate` is served by gpu-1 (the call appears in gpu-1's ledger under `node:desk:<id>`); the office shows the desk online | 2, 4 | running 2026-11-07: the first desk (`maluSlides-dev`, enrolled after install as desk 5) is on the overlay at 100.100.0.4; its gateway's grants had to be made by hand (the box predates the gateway's principal); `--prefer estate` served by gpu-1 |
| 6 | The cross-machine proof: a desk's personal agent delegates to an office agent whose model call lands on gpu-1 (three ledgers, one envelope); a document filed in DocCloud from a desk is found by the DocCloud Expert; a sharing rule at the office removes gpu-1 from a desk within a heartbeat | [13-estate.md](13-estate.md) §Proof, `maluos/docs/phase13-three-machine-proof.md` steps 3 and 4 | each check in the proof's list passes on real hardware; findings logged | 5 | planned |
| 7 | Reconciliation in the repositories: the README fixes, the docker archive, the kernel-off-by-default change, the `maluos-apps` component | [20-reconciliation.md](20-reconciliation.md), [21-maluos-apps.md](21-maluos-apps.md) | each decision has a commit or an issue; the next ISO installs an office with applications from a plan alone | findings of 1 to 6 | planned |

## Alternative compute paths

Start with the [compute roadmap](11-compute-roadmap.md) to choose the required
guides and their order. The numbered stages above retain the original test
history; new deployments follow the branch appropriate to their compute.

The completed stage 3 above records the original GPU-server proof. New
implementations can choose [cloud API compute](11-cloud-models.md), with
as many compatible hosts/accounts as needed, or [hybrid compute](11-hybrid-compute.md),
combining private models and cloud alternatives. These guides were added
November 9, 2026 from the gateway source; their provider and hybrid failure
tests are still to be run on a selected deployment. They do not change the
historical stage-3 status above.

Cloud-only model calls do not need a GPU node or inference-node enrolment.
Hybrid use of estate GPUs needs the stage-4 private-compute path first.
Estate membership does not share cloud credentials or credits: configure
cloud backends on each host originating those requests and verify that
the applications use that gateway. Desk and other estate functions retain
their own enrolment requirements.

### ARM compute on vendor operating systems

[ARM inference](11-arm-inference.md) adds the Apple Silicon Mac and DGX
Spark paths. Install the native runtime using the [Mac](11-gpu-macos.md)
or [Spark](11-gpu-dgx-spark.md) guide and prove GPU use and private
connectivity first. The November 9 repository review found that
`maluos-local-llm-server` has scheduler/store code but no real backend,
HTTP service or installer. Node-service deployment and MaluOS integration
therefore remain pending; these hosts are not part of the completed
stage-3/4 proof. Track host readiness separately from integration readiness.

## Distributed server-room placement

[Distributed applications](12-distributed-applications.md) describes a
separate database host, a central kernel host and one or more application
hosts, with domain-specific ingress routes. It is a deployment extension
to stages 1–2, not a completed result of the original single-office proof.
The guide identifies the local assumptions that must be removed from
provisioning before a split topology can survive routine updates. Its
migration, remote action/API, authentication and recovery checks remain
to be run against a selected deployment.

MaluOS now has a Phase 14 database-server plan, with the database reached
by its estate overlay name and later application-server roles. The plan
explicitly remains unimplemented in release 26.04.20261109. It does not
turn this staged extension into an automated or completed deployment.

## What the test does not cover

- The hand-install and docker paths for the kernel. Excluded.
- A live DGX Spark or Apple Silicon inference deployment. The new ARM
  guides cover preparation; the standalone node service and its network
  integration still need implementation and hardware validation.
- Editions, entitlements and the paid `scheduler` placement. The flag
  exists on the kernel's settings row; the test turns it on only for the
  proof's placement check.
- Backups, upgrades of a running estate, TLS on the servers themselves.

## Findings log

Append one row per finding while running the stages. A finding is a
step whose check did not match, a missing command, or a document that
said the wrong thing. The row names the stage, the machine, what was
expected, what was seen, and where it was filed.

| Date | Stage | Machine | Expected | Seen | Filed |
|---|---|---|---|---|---|
| 2026-11-05 | 1 | office | the runbook started from a plan served over HTTP and SSH into the live medium | the owner installed from the screens with the `maluos` account, as an operator will; no SSH into the live medium without `maluos.ssh=` on the boot line | runbook restructured: screens first, the domain by re-provision (§5), the plan as an appendix |
| 2026-11-05 | 1 | office | `systemctl is-active maluos-firstboot` says inactive when done | `active` both while running and after: the unit has `RemainAfterExit=yes` | runbook §4 checks `SubState` (`exited`) or the done file |
| 2026-11-05 | 1 | office | the 26.04.20261102 ISO provisions the kernel for `maluos.local` on a screens install | as expected; `maluctl provision --force` after editing firstboot.yaml re-rendered everything for tipdesk.org with the databases kept | maluos pull 3 (merged) makes the next ISO ask the domain |
| 2026-11-05 | 2 | office | DocCloud's activity MCP up after `app_install.php apply` | crash-looping on `int('')`: the manifest's two MCP endpoints lack `port_env`, so the installer left `MCP_ACTIVITY_PORT` empty; Spaces' manifest has the same gap | maludb-os-doccloud pull 1, maludb-os-spaces pull 1 |
| 2026-11-05 | 2 | office | the kernel reads the application's roles and lands the sign-on hand-off at `https://doccloud.tipdesk.org` | health unknown, hand-off 0: the VM cannot reach its own public names (no hairpin NAT on the LAN), so under `scheme: https` every application call from the kernel fails | the LAN DNS must resolve the nine names to the proxy's LAN address for LAN clients; handbook 30-reverse-proxy.md to say so |
| 2026-11-05 | 2 | office | the four defaults installed before DocCloud | not run; only DocCloud was installed | re-run after the name fix |
| 2026-11-05 | 2 | office | HR registers with the kernel like the other defaults | `answers` stopped: HR's `deploy/apache-hr.conf` carried the reference host's name and ports with no placeholders, so Apache served neither `hr.tipdesk.org` nor the assigned port; `install_default_applications.sh` exited after HR | maludb-os-hr pull (vhost as a template) |
| 2026-11-05 | 2 | office | `app_install.php apply` on a URL source reads the application's current manifest | it reuses a cached shallow clone under `/tmp/app-install-<hash>` from the first run, so DocCloud's fixed manifest was ignored on the re-run and the MCP ports stayed empty | maludb-os-core pull (fresh clone every run); on the office: remove the cache and re-run |
| 2026-11-05 | 2 | office | the installer's sign-on proof lands | `hand-off answered 0` on every application: under `--scheme https` the proof dials 127.0.0.1:443, where nothing listens when TLS ends at the proxy | maludb-os-core pull (the proof over :80 with X-Forwarded-Proto) |
| 2026-11-05 | 2 | office | DocCloud's health 200 after install | 503: `storage` unwritable because `/srv/apps/doccloud/storage` did not exist; the installer chowns `storage/` only when the checkout has it and DocCloud's `.gitignore` excluded it | maludb-os-doccloud pull (storage/.gitkeep); on the office: `install -d -o www-data` |
| 2026-11-05 | 3 | gpu-1 | the runbook's §1 to §6 as a sequence | §4 to §6 were already done by the dev work (Ollama, share on, exposed on the LAN); `maluos-nvidia` was absent because the driver had been installed by hand before installer 0.3.4; the dry run pulled only the signed 580 modules beside it | runbook holds; add the dry run |
| 2026-11-05 | 4 | office | `maluctl estate join` reaches the office at `https://app.tipdesk.org` | connection refused: first boot's loopback `/etc/hosts` line for `app.` under https; fixed by pointing the four kernel names at the proxy's LAN address | runbook §5b; maluos: the component should write the proxy's address or nothing under `scheme: https` (to file) |
| 2026-11-05 | 4 | office | the hub endpoint is the office VM's LAN address | the office is behind the proxy on its own network and the GPU server and desks are elsewhere, so the endpoint must be a public name with UDP 51820 forwarded to the VM; the first join used the LAN address and must be redone | handbook 13-estate.md §0 and 30-reverse-proxy.md rewritten |
| 2026-11-07 | 4 | office | `maluctl estate inference --refresh` as the operator's login, as the proof runbook shows it | the vault refuses the host's node token to a plain user and files a grant request; `sudo` is needed | maluos docs: `sudo` on the command in the proof and in `maluctl estate` usage (to file) |
| 2026-11-07 | 4 | gpu-1 | `gateway expose --bind overlay` reachable from the hub | timeout: ufw active with SSH only, dropping TCP 11435 on the `estate` interface; `ufw allow in on estate to any port 11435 proto tcp` fixed it | maluos: `expose --bind overlay` and `memory expose` should open their ports on the overlay interface under ufw, or say so (to file) |
| 2026-11-07 | 4 | gpu-2 | a spoke that joined before the hub existed exposes its gateway once the tunnel is up | `expose --bind overlay` before the address exists is refused and must be re-run by hand after the tunnel forms; the node's facts are published anyway, so the office sees a backend it cannot reach | runbook: expose after `ping office.internal` answers; maluos: queue the wish (`--force`) or expose on the tunnel's arrival (to file) |
| 2026-11-07 | 5 | desk | the enrolment grants the gateway and the memory face their rights on the desk's keys | `no principal user:maluos-gateway` / `user:maluos-memory`: the desk was provisioned before those components enrolled their principals; `maluctl provision --force` then the two grants by hand | runbook §1; maluos: the enrolment could run the provision step or say which command to run (to file) |
| 2026-11-07 | 5 | desk | a call targeted at one GPU node | `--prefer` knows only local, cloud, estate; `--prefer estate:gpu-2` is ignored and the ranking chose gpu-1; an alias cannot name an estate rung either (`maluos_alias_backend_fkey`: the rungs are not backend rows); no way to pin one estate node from a desk | runbook §1; maluos: a per-node `--prefer`, or estate rungs as alias targets (to file) |
| 2026-11-05 | 2 | office | clean installer output | PHP 8.5 `curl_close` deprecation lines from the kernel on every call; Apache's PHP warns `PCRE JIT memory` under the unit's hardening | kernel: drop `curl_close`; maluos: `pcre.jit=0` in the shipped PHP ini (to file) |

