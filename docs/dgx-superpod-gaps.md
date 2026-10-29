# Supporting the NVIDIA DGX SuperPOD architecture: design gaps (2026-10-29)

A gap analysis from the owner's ask of 2026-10-29: "we want to be able to
support this architecture", pointing at NVIDIA's *DGX SuperPOD Solution
Overview* (resources.nvidia.com/en-us-dgx-systems/dgx-ai-4, a
password-protected PDF; the architecture below is taken from NVIDIA's
public reference architectures for the DGX B300, DGX GB300 and DGX Rubin
NVL8 SuperPODs, listed under Sources). Nothing here is built or decided;
the three tiers at the end are the recommendation, and the decisions the
owner must make come before any slice is specified.

## 1. What the architecture is

A DGX SuperPOD is NVIDIA's turnkey AI data centre: a modular cluster of
DGX systems, four physical networks, partner storage and a management
stack, sold and supported as one unit (NVEX support covers compute,
network, storage and Mission Control).

| Layer | What NVIDIA specifies |
|---|---|
| Compute node | DGX B300 (air-cooled, x86 Xeon, 8× Blackwell Ultra, 2.1 TB HBM3e, NVLink 5 + NVSwitch 4, ConnectX-8 SuperNICs at 800 Gb/s, BlueField-3 DPUs); DGX GB300 and Vera Rubin NVL72 (Grace **arm64**, liquid-cooled, 72 GPUs in one NVLink domain per rack); DGX Rubin NVL8 (ConnectX-9, BlueField-4, DC busbar, liquid-cooled) |
| Scalable Unit (SU) | 72 DGX systems (576 GPUs); a tested system is 8 SUs for B300 (4,608 GPUs) and 16 SUs for Rubin NVL8; up to 4 B300 or 8 Rubin systems per rack |
| Compute fabric (east-west) | Quantum-X800 InfiniBand at 800 Gb/s (or Spectrum-X Ethernet), rail-optimised, non-blocking, twin-plane fat tree; adaptive routing, SHARP in-network collectives, SHIELD self-healing; managed by UFM appliances |
| Storage fabric | NDR InfiniBand (QM9700) or RoCE on Spectrum-4 (SN5600D), independent of the compute fabric |
| In-band management (north-south) | Spectrum-4 Ethernet, 200 to 400 Gb/s bonded per node: provisioning, data movement, Internet, user services |
| Out-of-band management | SN2201 at 1 Gb/s to every BMC; a Switch Management Network with Zero Touch Provisioning; physically isolated from users; its own uplink handover |
| High-performance storage | a certified partner's POSIX parallel file system with RDMA, RAM and local flash caching (DDN, VAST, WEKA, NetApp, Pure, IBM in practice); topology set by the partner |
| User storage | NFS on the in-band network at 100 Gb/s or more: home directories, admin scratch, BCM high-availability state, logs; checkpoint-oriented |
| Management software | **NVIDIA Mission Control** = Base Command Manager (bare-metal provisioning, node categories, software images, HA head nodes, Slurm and Kubernetes set-up, monitoring) + **Run:ai** (fractional, full and multi-node GPU jobs for interactive, training and inference) + **UFM** (fabric), plus cluster health checks, predictive maintenance, unified error reporting, automated node management, cluster-wide telemetry |
| Node software | **DGX OS** (Ubuntu-based): data-centre driver branch, Fabric Manager and NSCQ for NVSwitch, DCGM, DOCA and MOFED for the NICs and DPUs, nvidia-peermem and GPUDirect Storage, NVSM, the container toolkit; Slurm; Kubernetes with the GPU and Network Operators; NVIDIA AI Enterprise (NIM, Triton, TensorRT-LLM, NeMo); NGC containers; Magnum IO (NCCL, GDS) |
| Tenancy and support | "multitenancy is not supported with SuperPOD currently"; multi-team through BCM only; NVEX supports the whole stack **as shipped** (DGX OS + Mission Control) |
| Facilities | N+N power shelves or DC busbar, liquid cooling, building management system integration, owned by the customer |

Two facts shape everything below. The compute data paths (NCCL over
InfiniBand, RDMA to storage) never touch an IP overlay; and the whole
management stack is a product NVIDIA sells with the hardware and supports
only in its own form.

## 2. Where MaluOS stands today

What Phases 6 and 13 give us, read against the table above
(docs/phase6-inference-gateway.md, docs/phase13-shared-gpus.md,
docs/phase13-estate.md, docs/phase13-slice1-nodes.md,
docs/phase13-slice1b-overlay.md, docs/phase13-slice3-inference.md,
docs/inference-node-api.md, docs/components.md):

- **Architecture: amd64 only.** arm64 is roadmap idea E6. The DGX B300 is
  x86; the GB300, Vera Rubin NVL72 and DGX Spark are Grace (arm64).
- **GPU stack: the desktop driver.** The `nvidia` component installs the
  Canonical-signed generic-kernel modules of the 595/580 *desktop*
  branches, nvidia-smi and nvtop; no data-centre branch, no Fabric
  Manager (an 8-GPU NVSwitch system does not expose its GPUs to CUDA
  without it), no DCGM, no MOFED/DOCA, no peermem, no GDS, no container
  toolkit. `maluctl gpu status` reads utilisation, VRAM, temperature,
  power and compute capability through nvidia-smi.
- **Inference engine: Ollama.** The gateway's backend kinds are
  `ollama_local`, `ollama_cloud`, `anthropic`, `openai`, `openai_compat`
  and (G2) `remote`. Phase 6 assumes "one local model on one GPU"; there
  is no vLLM, TensorRT-LLM, NIM or Triton adapter, no tensor- or
  pipeline-parallel placement, no multi-node serving, no model replicas.
- **Scheduling: a queue in front of models.** Classes, affinity, expected
  wait, budgets, the ledger, per-principal limits; G4/D3 adds estate-wide
  placement with a lease as the paid `scheduler`. Nothing for batch
  training jobs: no partitions, reservations, job arrays, multi-node
  allocation, fair share, pre-emption, checkpoint awareness.
- **The estate: one coordinator, a company's machines.** Node kinds
  `desk`, `server`, `inference`; one node is one machine; heartbeat
  60 s, report 300 s; a WireGuard hub-and-spoke overlay through the
  coordinator's host (100.100.0.0/16) for node-to-node traffic; the
  directory and the envelope (slice 2); health rules `agent_down`,
  `vault_alert`. Designed for tens of nodes, not 576.
- **Provisioning: an ISO per machine.** The installer takes a plan from
  the medium (unattended) or asks; PXE netboot, arm64 media and an
  estate-enrolled install are listed as later in docs/phase11-installer.md.
  No BMC/Redfish, no image-based bare-metal provisioning, no node
  categories, no HA head nodes.
- **Identity: the vault.** Principals, host principals, Linux users
  mapped to principals per host; no LDAP/AD, no SSO (a paid edition
  idea), no uniform UID/GID across nodes, which Slurm and a shared parallel
  file system require.
- **Storage: deliberately not designed** (the owner's larger plans,
  docs/phase13-shared-gpus.md "Not object storage").
- **Observability: the System Monitor fork and the estate report.** Live
  per-host GPU facts at 2 s locally, in the report every 5 minutes; no
  fabric telemetry, no Xid/ECC/row-remap/NVLink health, no per-job GPU
  accounting, no firmware inventory.
- **Strengths that carry over:** departments and budgets per principal
  (the multi-team model BCM offers), an auditable ledger with origin
  node and envelope on every remote call, "connectivity is not
  permission", the one node API for every inference node, and the
  Sovereign LLM Manager as the fleet's manager.

## 3. The gaps, by layer

Each row names the SuperPOD element, what we have, the gap and the tier
(§4) that needs it closed. "A" is consuming a SuperPOD as an inference
provider, "B" is operating beside it as the estate's control plane and
observer, "C" is MaluOS as the node operating system.

### 3.1 Platform and drivers

| SuperPOD element | MaluOS today | Gap | Tier |
|---|---|---|---|
| Grace arm64 nodes (GB300, Vera Rubin, DGX Spark) | amd64 only | an arm64 build of every profile (E6): the repo, the rootfs and ISO scripts, the kernel, the boot test under TCG; MaluOS' NVIDIA bits then also need the arm64 driver packages | C (and A for a Spark-class node running MaluOS) |
| Data-centre GPU driver, open kernel modules | desktop 595/580 generic modules | an `nvidia-datacenter` component: the `-server` branch (or open modules), pinned to the DGX firmware matrix, Secure Boot story for modules Canonical does not sign | C |
| NVSwitch: Fabric Manager, NSCQ, `nvidia-fabricmanager` service | none | the service, its state in `maluctl gpu status` (fabric state, NVLink partition), boot ordering before the gateway | C |
| DCGM (health, Xid, ECC, row remap, NVLink errors, per-process accounting) | nvidia-smi fields | a DCGM reader beside the nvidia-smi one in maluos_gpu.py; health rules in the estate report; per-job accounting into the ledger | B (reader through the DCGM exporter), C (local) |
| ConnectX-8/9 and BlueField-3/4: MOFED or DOCA-OFED, rdma-core, DPU host side | nothing RDMA | the DOCA/OFED component, RDMA facts (`ibstat`, link state, rail), the DPU as a managed device | C |
| GPUDirect RDMA and Storage (nvidia-peermem, nvidia-fs), GDRCopy | none | packages and their kernel modules; only matters once a parallel FS client exists | C |
| Container toolkit, NGC, GPU Operator | agents run as hardened systemd units; no containers | nvidia-container-toolkit, a container runtime policy under the vault (which image, which model, which principal) | B (for jobs we submit), C |
| NVSM and the DGX firmware bundle (BMC, VBIOS, NIC, NVSwitch) | none | firmware inventory in the report; an update orchestration that drains a node first; or simply "firmware stays NVIDIA's" | C |

### 3.2 Inference serving

| SuperPOD element | MaluOS today | Gap | Tier |
|---|---|---|---|
| NIM / Triton / TensorRT-LLM / vLLM serving many GPUs | Ollama, one model one GPU | an engine adapter per engine (OpenAI-compatible faces exist for all of them; the gap is the *node side*: health, loaded models, lanes, queue depth, `since_seq` runs) so a serving cluster speaks `/node/v1` | A |
| One endpoint fronting N GPUs on N nodes (replicas, tensor parallel) | a lane is one backend with `capacity` | the node API's `lanes{}` and `machine.gpus[]` assume one machine; add `replicas`, `parallelism`, `nodes[]` and a `cluster` node kind whose `/status` aggregates members | A |
| Run:ai or Kubernetes placing inference services | the gateway's scheduler ranks rungs by expected wait | a backend whose capacity is *elastic* (a Run:ai workload scaled by queue depth): the scheduler must read `capacity: null` as "ask and wait", and the `scheduler` edition's `place` lease must survive autoscaling | A (Community can treat it as one big lane), B |
| Batch inference over hours (evaluation, embedding a corpus) | async jobs kept 72 h in memory, 1000 finished jobs | durable jobs in PostgreSQL, result files on storage, a `batch` class with a deadline, resumable `since_seq` on job events (listed as later in the API) | A |
| North-south path at 200 to 400 Gb/s | every estate rung dials `NAME.internal` through the coordinator's WireGuard hub | the overlay cannot carry a SuperPOD's traffic: an estate rung needs a **direct route** option (the in-band network's address, mTLS or the node key, no hub), with the overlay kept for control; the no-chains rule stays | A |
| Authentication for a shared cluster | bearer keys, shown once | mTLS or OIDC-issued keys so a 500-desk estate does not mint 500 inference keys by hand; G4's "node key as estate credential" covers MaluOS members, not Run:ai's own auth | A |

### 3.3 Workload management (training and batch)

| SuperPOD element | MaluOS today | Gap | Tier |
|---|---|---|---|
| Slurm partitions, multi-node jobs, Pyxis/Enroot containers | nothing | a `slurm` connector in the estate: an agent or a person submits through the kernel (`sbatch` with the envelope recorded), job state and accounting (`sacct`) flow back into the ledger per department; MaluOS does **not** run slurmctld | B |
| Kubernetes with the GPU and Network Operators | nothing | a `kubernetes` connector of the same shape (a namespace per department, a ServiceAccount per agent) | B |
| Fair share, pre-emption, reservations, checkpoint-restart | classes and expected wait | out of scope for the gateway; mapped onto Slurm/Run:ai policies through the connector; an estate operator's rules (G4 decision 7) become Slurm QOS or Run:ai projects | B |
| Multi-team quotas (BCM's model) | departments, budgets, a ledger per principal | the mapping: `dept:N` ⇄ Slurm account / Run:ai project / k8s namespace, uniform UID/GID (below), and the chargeback statement deferred to slice 5 | B |

### 3.4 Provisioning and lifecycle (what Base Command Manager does)

| SuperPOD element | MaluOS today | Gap | Tier |
|---|---|---|---|
| Bare-metal provisioning of 576 nodes from a head node (PXE, images, node categories) | an ISO with a plan; PXE is "later" | a netboot service (iPXE, the plan from a URL, the squashfs from apt.maluos.com), **node categories** (an image + plan per role), image-based reinstall, enrolment at first boot into the estate with a pre-minted code per node | C (B only for our own management nodes) |
| HA head nodes, shared NFS state | one coordinator, the Business OS kernel on one server; a second hub "later" | an active/passive coordinator with PostgreSQL replication and a floating address; the overlay hub moving with it | B |
| Out-of-band: BMC/Redfish inventory, power control, console | none | a Redfish reader in the estate (power state, sensors, SEL events, firmware versions), `maluctl estate node power on|off|cycle`, the OOB network as a known interface class | B (read), C (control) |
| Switch management, ZTP, UFM | none | a UFM REST reader (fabric health, port errors, SHARP state) into the estate report and the Network tab; switch ZTP stays NVIDIA's | B |
| Node health checks, automated node management, predictive maintenance | `agent_down`, `vault_alert` | node states (`healthy`, `draining`, `drained`, `failed`), a drain that empties the gateway's lanes and Slurm's jobs, health rules from DCGM/UFM/Redfish facts, an operator action on the Network tab; prediction later | B |
| Cluster-wide telemetry (Prometheus-shaped) | the report every 5 minutes | ingestion of the DCGM, node, UFM and Slurm exporters that a SuperPOD already runs; retention in the kernel's PostgreSQL or a TSDB; a dashboard in Settings → Estate | B |
| Software image lifecycle (DGX OS releases, driver + firmware matrix) | `maluctl update`, the Upgrade Manager | nothing to do at tier A/B; at tier C the whole DGX release cadence becomes ours | C |

### 3.5 Networking

| SuperPOD element | MaluOS today | Gap | Tier |
|---|---|---|---|
| Four networks with distinct roles | one address per node on the overlay, the LAN for pairing | the node record gains **interfaces with roles** (`inband`, `oob`, `storage`, `compute`); the gateway binds and advertises per role (`expose --bind inband`); the estate never routes compute or storage traffic | A, B |
| Rail-optimised InfiniBand, adaptive routing, SHARP | none | nothing for MaluOS to do unless tier C; at B, read-only facts from UFM | B (read) |
| Twin-plane 800 Gb/s | WireGuard hub through one host | see 3.2: direct routes; the hub is control-plane only | A |

### 3.6 Storage

| SuperPOD element | MaluOS today | Gap | Tier |
|---|---|---|---|
| Parallel file system with RDMA | not designed, by the owner's decision | a `storage` role in the estate (mounts a node must have, by category), the partner client as a component (Lustre, GPFS, VAST/WEKA clients each have kernel modules or FUSE); GDS needs 3.1 | C (client), B (facts only) |
| NFS user storage: home directories, checkpoints | none | a `home` mount per node by category with uniform UIDs; this is the first storage decision the owner has to make, and it is small | B |
| Model stores (weights shared by every serving node) | Ollama's per-host store, `ollama.pull` at first boot | a shared model repository (an NFS or object path the engine reads), model pulls "on demand across the estate" (deferred in slice 3) | A |

### 3.7 Identity and security

| SuperPOD element | MaluOS today | Gap | Tier |
|---|---|---|---|
| Uniform users across nodes (Slurm, NFS, k8s) | a Linux user per host mapped to a principal | an estate-wide directory of UIDs/GIDs: SSSD against LDAP/AD or the kernel as the source (`sso` edition); host principals already exist | B |
| Isolated OOB and switch management networks | none | the interface roles of 3.5 and a firewall policy per role in the base profile | B |
| BlueField as a security boundary (DOCA: telemetry, encryption, threat detection) | none | nothing at A/B; at C the DPU is a second managed host per node | C |
| The envelope, "connectivity is not permission" | built (slice 2) | carry it through the Slurm/k8s connectors (job metadata) so a SuperPOD job is attributable to a person, an agent and a department | B |

### 3.8 Scale and the operator's view

| SuperPOD element | MaluOS today | Gap | Tier |
|---|---|---|---|
| 576 nodes, 4,608 GPUs, 8 SUs | the estate directory and report for tens of nodes; three GTK tabs | a `cluster` node that reports *aggregates* (per SU, per partition) instead of 576 heartbeats; the Network and Queue tabs show the cluster as one row and open the detail in the Sovereign LLM Manager, as decided for history | A, B |
| Heartbeat and report volume | 60 s / 300 s per node | if member nodes do report individually: batching, partitioning of the `locations` tables, retention; otherwise avoided by the aggregate node | B |
| Facilities: power shelves, liquid cooling, BMS | none | out of scope at every tier; at most Redfish sensors through 3.4 | none |

### 3.9 Commercial and support

| SuperPOD element | MaluOS today | Gap | Tier |
|---|---|---|---|
| NVEX supports DGX OS + Mission Control as shipped | n/a | replacing DGX OS or Mission Control on a supported SuperPOD moves the customer off NVIDIA support; tier C is only sellable to a customer who accepts that, or on DGX-class hardware bought without the SuperPOD contract | C |
| NVIDIA AI Enterprise licensing (NIM, Run:ai) | n/a | tier A consumes it; the estate must not re-license or proxy it in a way the EULA forbids (serving NIM to third parties); a legal read before shipping | A |
| Editions | `scheduler` paid (G4), `fleet` and `sso` named | the connectors (Slurm, k8s, UFM, DCGM, Redfish) and the HA coordinator are `fleet`; the directory of users is `sso`; tier A stays Community for the adapter and `scheduler` for placement | A, B |

## 4. Three tiers, and the recommendation

| Tier | Meaning | What it needs (from §3) | Size |
|---|---|---|---|
| **A: Consume** | a SuperPOD (or any DGX cluster running NVIDIA's stack) is an inference provider of the estate, registered as one `inference` node through the node API; desks and agents use it like a shared GPU host | G3's node service grown into a cluster-aware implementation (engine adapters for NIM/vLLM/TRT-LLM, the `cluster` node kind, replicas and parallelism in `lanes`, durable batch jobs), direct routes beside the overlay, interface roles, mTLS or OIDC keys, a shared model store, the legal read | L; two or three slices in two repositories (maluos-local-llm-server for the node side, this one for the API and the gateway) |
| **B: Operate beside** | MaluOS servers are the estate's control plane and the operator's window *next to* Mission Control: agents and people submit Slurm/Run:ai/k8s work through the kernel with the envelope; the estate reads DCGM, UFM, Redfish and Slurm; node states, drain, HA coordinator, uniform identity, NFS home | the connectors, the telemetry ingestion, the Redfish and UFM readers, node states and drain, the HA coordinator, SSSD/LDAP, the `fleet` and `sso` editions | XL; a phase of its own (Phase 14, "the data centre"), after Phase 13 |
| **C: Replace DGX OS** | MaluOS is the node operating system of a DGX system or a SuperPOD, and the estate replaces Base Command Manager | arm64, the data-centre driver, Fabric Manager, DCGM, DOCA/OFED, GDS, the container toolkit, PXE and image provisioning with node categories, firmware lifecycle, parallel FS clients, DPU management, and NVIDIA's release cadence as ours; loses NVEX support | XXL; it is rebuilding Mission Control |

**Recommendation.** Tier A now, as the natural widening of G3 and G4
(a DGX cluster is a very large `inference` node); tier B as Phase 14
once Phase 13 closes, since every one of its pieces (connectors, node
states, HA, identity) is useful for an ordinary company data centre too;
tier C explicitly out of scope unless the owner has a customer who wants
MaluOS on DGX-class hardware outside NVIDIA's support model. The one
piece of tier C worth pulling forward on its own merits is the arm64
build (E6): it is what lets a DGX Spark, a GB300 or a Grace server be a
MaluOS node at all, and it is a precondition for nothing else in tier A.

## 5. Decisions for the owner

1. **Which tier is meant by "support this architecture"?** A, A+B, or C.
   Everything in §3 is sized against that answer.
2. **Storage.** Tier B needs one small storage decision (NFS home with
   uniform UIDs); the owner asked that storage stay out of the GPU round.
   Is a `home` mount role acceptable now, or does it wait for the larger
   storage plan?
3. **Identity.** Does the kernel become the source of Linux UIDs/GIDs
   across the estate (SSSD against the kernel or an LDAP it publishes), or
   does MaluOS join a customer's existing AD? This decides the `sso`
   edition's shape.
4. **The direct-route exception to "over the overlay, always"** (slice 3
   decision 3): allow an estate rung to dial an in-band address with mTLS
   when both ends are servers on the same site, keeping the overlay for
   desks and control.
5. **arm64 (E6)** pulled forward or not.
6. **Edition lines** for the connectors, the HA coordinator and the
   directory of users (`fleet`, `sso`), per §3.9.

## 6. Staying on DGX OS: the POD as a node of the estate (2026-10-29)

The owner's follow-up: DGX OS and Mission Control stay as NVIDIA ships
them; what do we create so the POD is *in* the estate? The answer is a
**bridge**, not an agent on every DGX node. Two facts make it small:

- Every estate package (maluos-estate, maluos-gateway, maluos-vault,
  maluos-agent, maluos-firstboot, maluos-tools) is `Architecture: all`
  Python ≥ 3.12 with Debian dependencies DGX OS already has (aiohttp,
  psycopg, cryptography, wireguard-tools). They install unchanged on a
  DGX OS or BCM management node, or on a small MaluOS server beside the
  POD. No arm64 build is needed for the bridge.
- Everything the POD knows about itself is already served by NVIDIA's
  APIs: Base Command Manager (cmsh, the pythoncm/REST API), slurmrestd,
  the Run:ai REST API, the Kubernetes API, UFM REST, the DCGM exporter
  (Prometheus on every node), Redfish on every BMC, and NIM/Triton/vLLM's
  OpenAI faces and `/metrics`. The bridge reads them; it never replaces
  them.

### 6.1 Where the bridge runs

A **MaluOS server, `maluos-pod` installed, on the POD's in-band
management network with an overlay address** (a VM or a 1U box; the
kernel's own host can double as it for a small site). Alternative, once
the packages are proven: the same packages on a BCM login or management
node (DGX OS, x86), which keeps the data path on one host but puts our
packages on a machine NVIDIA supports. Recommendation: the dedicated host
first; it costs nothing in NVEX support and the image chain already
tests it.

### 6.2 What to create

| # | Piece | Where | What it is |
|---|---|---|---|
| 1 | **Node kind `pod`** | kernel (a db/19x change beside slice 3's db/191) | a node whose facts are aggregates: `pod: {vendor, product (DGX SuperPOD B300), sus[], nodes {total, up, drained, failed}, gpus {total, allocated, idle}, fabric {state, ports_down, sharp}, partitions[] (Slurm) / projects[] (Run:ai) with queued and running jobs, storage {hps, user} capacity}`; `maluctl estate join URL --code CODE --kind pod --name pod-1`; Settings → Estate → Pods; health rules `pod_node_down`, `pod_gpu_xid`, `pod_fabric_degraded`, `pod_queue_stalled` → the operator's desk as today's alerts |
| 2 | **maluos-pod**, the bridge package | this repository | `maluos-podd` collects every `report_s` from the sources it is configured with (`/etc/maluos/pod.yaml`: BCM, slurmrestd, Run:ai, k8s, UFM, DCGM exporter or the POD's Prometheus, Redfish) and writes the `pod` facts into the estate report that maluos-estate already sends; operator actions (`maluctl pod node drain|resume NAME`, `maluctl pod job cancel ID`, `maluctl pod service scale NAME N`) run through BCM/scontrol/Run:ai with the envelope ledgered; credentials to those APIs live in the vault under the host principal |
| 3 | **A `nim` backend kind** in the gateway (or `openai_compat` with a `location: local\|remote\|cloud` field: today `openai_compat` is treated as *cloud* and would be gated as such, which is wrong for an on-premises POD) | maluos-gateway | one lane per served model service: health from its OpenAI face, queue depth and loaded model from `/metrics` (NIM, Triton and vLLM all export Prometheus), `replicas` and `parallelism` in `lanes{}` of the node API, capacity `null` for an autoscaled Run:ai service; the bridge's gateway thereby serves the POD's inference to the estate through `/node/v1` and the estate rung `estate:pod-1` of slice 3 — desks dial the bridge over the overlay (chat traffic is light), the bridge dials NIM over the in-band network at 200 Gb/s; the no-chains rule stands because the bridge is the serving host |
| 4 | **The work connector** | maluos-pod + kernel (slice 5's durable task tables) | an estate task becomes a Slurm job (`sbatch` through slurmrestd) or a Run:ai workload (REST): the envelope id, principal and department go into the job comment or labels; `dept:N` maps to a Slurm account / Run:ai project by a table in the kernel; job state is polled back into the task record; `sacct` and Run:ai metrics write GPU-hours into the ledger per department (the chargeback statement of slice 5); results land on the POD's user storage and are referenced, not copied; exposed to agents as the MCP tool `pod.submit` and as an A2A task kind, so a specialist agent on the office server can hand training or batch work to the POD under the envelope |
| 5 | **The identity map** | kernel + vault | estate members and departments map to POD users and accounts in BCM's LDAP (`estate_pod_identity`); the bridge submits as a per-department service user whose credential is in the vault; no UID unification across the estate, no SSSD: the POD keeps its directory |
| 6 | **The operator's view** | maluos-system-monitor, kernel, Sovereign LLM Manager | the Network tab shows a POD as one row with its SU breakdown and health; the Queue tab shows its lanes as any backend's; the detail (per-node, per-job, history) is Settings → Estate → Pods and the Sovereign LLM Manager, as decided for history in G5 |
| 7 | **The model store** | maluos-pod | the catalogue of models the POD serves is read from NIM/Run:ai, not pulled by us; `maluctl pod models` lists them; an operator deploys a new NIM through Run:ai and the bridge picks it up at the next refresh (`inference_changed`) |

Not created: provisioning, images, firmware, fabric management, the
Slurm or Kubernetes control planes, parallel storage clients, DGX OS
packages. All of it stays Mission Control's.

### 6.3 Slices

| # | Slice | Gives | Needs | Size |
|---|---|---|---|---|
| P1 | **Observe**: kind `pod`, the bridge's collectors (BCM or slurmrestd, DCGM exporter, UFM), the report, the health rules, the Pods page and the Network tab row | the POD appears in the estate with live health and alerts | D1 (built), a mock POD (fake slurmrestd + DCGM exporter) for the image chain | M |
| P2 | **Serve**: the `nim` kind with metrics, replicas in the node API, the bridge as the estate's inference node | every desk and agent uses the POD's models through its own gateway socket; the Sovereign LLM Manager manages it with the others | G2 (built), G4/D3 for the directory (else pairing by hand works today) | M |
| P3 | **Submit**: the work connector, the identity map, GPU-hours into the ledger, `pod.submit` and the A2A task kind | agents and people hand training and batch work to the POD under the envelope, billed to departments | D2 (built), D5 for durable tasks | L |
| P4 | **Operate**: drain/resume, cancel, scale, with the envelope; the bridge in HA (two bridges, one active, the kernel picks) | the system manager acts on the POD from the Network tab | P1, P3 | M |

Editions: P1 and P2 Community (a POD as an inference node is what G3
promised for non-MaluOS nodes, and the owner's rule of 2026-10-25 was
Community first for sharing); P3 and P4 are `fleet`, estate-wide
placement over several PODs is `scheduler` as in slice 3.

### 6.4 Decisions for the owner

1. Bridge on a MaluOS host first (recommended) or on a BCM management node.
2. Slurm or Run:ai as the first connector in P3 (a SuperPOD with Mission
   Control has both; Run:ai is the inference-service side, Slurm the
   training side).
3. Whether GPU-hours from the POD are billed to departments in the
   ledger from P3, or only recorded.
4. The `nim` kind as a new kind, or `location` on `openai_compat`.

### 6.5 How well the sources are documented (checked 2026-10-29)

What the bridge would read, and the state of each source's public
documentation. Ratings: **good** = a complete reference with a
machine-readable spec or an exhaustive metric list; **usable** = enough
to build on with the product in front of us; **thin** = no public
programmatic reference.

| Source | Used by | Documentation | Rating | Caveats |
|---|---|---|---|---|
| **DCGM exporter** (Prometheus on every node) | P1 health, P2 GPU facts | NVIDIA's reference lists every default and optional field (`DCGM_FI_DEV_GPU_UTIL`, `DCGM_FI_DEV_XID_ERRORS`, ECC, row remap, NVLink, `DCGM_EXP_XID_ERRORS_TOTAL`); CSV and YAML config documented; the exporter is open source | good | profiling fields (`DCGM_FI_PROF_*`) are off by default; `GPU_UTIL` means "a kernel was running", not capacity |
| **slurmrestd** (SchedMD, not NVIDIA) | P3 submit, P1 partitions and queues | the OpenAPI spec is generated from the installed daemon (`slurmrestd --generate-openapi-spec`), so it always matches the version; submit, list, cancel and the `slurmdb` accounting namespace are stable; JWT auth (`X-SLURM-USER-NAME`/`-TOKEN`, `scontrol token`) documented | good | the API version string (`v0.0.42`, `v0.0.43`) changes with each Slurm release; pin it per POD; the accounting routes are less exemplified than submit |
| **NIM / vLLM / Triton metrics** | P2 lanes (queue depth, cache, loaded model) | per-release observability pages list the metrics (`num_requests_waiting`, `gpu_cache_usage_perc`, …); OpenAI face documented | good | the path moved from `/v1/metrics` to `/metrics` between releases; metric names vary slightly across NIM, vLLM and Triton, so the `nim` kind needs a small per-engine mapping |
| **Run:ai REST API** | P2 inference services (autoscaled lanes), P3 submit (workloads) | a full reference site per version (2.21 to 2.26, SaaS and self-hosted): Workloads V2, inferences, per-workload and per-pod metrics, NIM metrics via API; bearer-token auth | good | Workloads V2 *create* is marked experimental; endpoints are version-gated (inference metrics from 2.18); two deployment flavours; the docs are the SaaS product's, so confirm the self-hosted control plane a SuperPOD ships |
| **Base Command Manager REST and Python APIs** | P1 inventory (racks, SuperPods, GPUs, NVLink, InfiniBand, drain state, jobs, chargeback), P4 power and drain | a Developer Manual (BCM 10 and 11) with a REST chapter: v1 read-heavy with worked examples and a thorough monitoring section; v2 entity CRUD; Swagger UI on the head node (`/api/rest/swagger/`) and `openapi.json` installed under `/cm/local/docs/cmd/rest/`; pythoncm documented in its source with examples on the head node | usable | v2 is **off by default** (`RestV2Enabled=1`) and needs profile tokens whose creation the manual defers to the Administrator Manual; v1 writes are narrow (power, status, events, mlxconfig); no error reference, pagination or rate guidance; the full schema lives only on an installed head node, so we cannot read it before we have access to one; BCM 10 and 11 differ |
| **UFM Enterprise REST API** | P1 fabric health | a REST API guide per release (6.9 to 6.24): Reports (`Fabric_Health`), periodic fabric health (`ufmRestV2/periodic_health/last_report`), Monitoring and History Telemetry, Unhealthy Ports | usable | flags and routes differ between minor releases; it is a licensed appliance, so the version is whatever the POD shipped with; telemetry is a 5-minute history session, fine for our 300 s report |
| **Redfish on the BMCs** (DMTF) | P1 sensors and SEL, P4 power | the DMTF standard and schemas are complete and public; BCM also fronts Redfish for its nodes | good | each BMC vendor's OEM extensions differ; power and firmware actions are the risky part and belong to P4 only |
| **Mission Control: health checks, autonomous hardware and job recovery** | nothing we build on | a Systems Administration Guide (2.0 to 2.3.1) describes behaviour (prolog checks drain the node and requeue the job; periodic checks are alarms in the AHR UI); the API is a third party's (Shoreline, `ssapi.shorelinesoftware.net`) referenced but not published on docs.nvidia.com | thin | automated health checks and break/fix are GB200-only in 2.3.1 (GB300 firmware upgrades only); treat Mission Control as a black box whose *effects* we see through Slurm node states and BCM events, never as an API we call |

**What this means for the slices.** P1 and P2 rest on the four "good"
sources (DCGM, slurmrestd, the engines' metrics, Run:ai) plus read-only
BCM v1 and UFM, all of which can be mocked from their published shapes
for the image chain. P3 should start with **Slurm**, whose self-generated
OpenAPI spec is the most stable contract in the list, with Run:ai
Workloads V2 behind a flag until it leaves "experimental". P4's writes
(BCM v2, Redfish power) are the only part where the documentation is not
enough on its own: they need a head node to read `openapi.json` from and
an administrator to enable v2 and mint tokens, so P4 waits for access to
a real POD or a BCM evaluation. Nothing should be built against Mission
Control's own API. Across every source the versions sprawl, so
`/etc/maluos/pod.yaml` names each source's version and the collectors
carry one adapter per major version, as the gateway does for its cloud
providers.

## Sources

- NVIDIA DGX SuperPOD documentation index: https://docs.nvidia.com/dgx-superpod/index.html
- DGX SuperPOD with DGX Rubin NVL8 systems, key components: https://docs.nvidia.com/dgx-superpod/reference-architecture/scalable-infrastructure-rubinx86/latest/dgx-superpod-components.html
- DGX SuperPOD with DGX B300, Quantum-X800 InfiniBand and AC power, reference architecture: https://docs.nvidia.com/dgx-superpod/reference-architecture/scalable-infrastructure-b300-xdr/latest/
- DGX SuperPOD with DGX GB300, reference architecture (PDF): https://docs.nvidia.com/pdf/dgx-spod-gb300-ra.pdf
- DGX B200 and B300 BasePOD and SuperPOD deployment guides with NVIDIA Mission Control: https://docs.nvidia.com/dgx-basepod/deployment-guides/dgx-basepod-b200/latest/index.html
- NVIDIA Spectrum-X validated solution stack: https://docs.nvidia.com/networking/software/spectrumx-solution-stack/index.html
- NVIDIA newsroom, Blackwell Ultra DGX SuperPOD: https://nvidianews.nvidia.com/news/blackwell-ultra-dgx-superpod-supercomputer-ai-factories
- NADDOD, DGX B300 SuperPOD system architecture (Ethernet and InfiniBand): https://www.naddod.com/ai-insights/dgx-b300-superpod-system-architecture-introduction-based-on-ethernet-and-infiniband-networking
- Data Center Dynamics on the Blackwell Ultra SuperPOD: https://www.datacenterdynamics.com/en/news/nvidia-announces-latest-superpod-with-blackwell-ultra-gpus/
- BCM 11 Developer Manual, REST API chapter: https://docs.nvidia.com/base-command-manager/product-manuals/developer/restapi.md and Python API: https://docs.nvidia.com/base-command-manager/product-manuals/developer/pythonapi.md
- Run:ai REST API reference: https://run-ai-docs.nvidia.com/api and Workloads V2: https://run-ai-docs.nvidia.com/api/workloads/workloads-v2 and NIM metrics via API: https://run-ai-docs.nvidia.com/api/api-guides/nim-observability-metrics-via-api
- UFM Enterprise REST API Guide (6.24.2): https://docs.nvidia.com/networking/display/ufmenterpriserestapi/Reports+REST+API and periodic fabric health: https://networking-docs.nvidia.com/ufmenterpriserestapi/6242/periodic-fabric-health-rest-api
- Mission Control Systems Administration Guide: https://docs.nvidia.com/mission-control/docs/systems-administration-guide/latest/index.html ; autonomous hardware recovery: https://docs.nvidia.com/mission-control/docs/systems-administration-guide/2.2.0/autonomous-hardware-recovery.html ; AHR installation (2.3.1, GB200-only note): https://docs.nvidia.com/mission-control/docs/nmc-software-installation-guide/2.3.1/nmc-ahr-installation.html ; BCM manual's AHR chapter: https://docs.nvidia.com/base-command-manager/product-manuals/nvidia-mission-control/ahr
- NIM for LLMs observability: https://docs.nvidia.com/nim/large-language-models/1.14.0/observability.html
- DCGM exporter metrics reference: https://docs.nvidia.com/datacenter/dcgm/latest/reference/dcgm-exporter-metrics.html
- slurmrestd: https://slurm.schedmd.com/slurmrestd.html ; SchedMD REST API slides (SC24): https://slurm.schedmd.com/SC24/REST-API.pdf ; JWT: https://third-party-mirror.googlesource.com/SchedMD/slurm/+/refs/heads/master/doc/html/jwt.shtml
- The original link (password-protected PDF, "NVIDIA DGX SuperPOD Solution Overview"): https://resources.nvidia.com/en-us-dgx-systems/dgx-ai-4
