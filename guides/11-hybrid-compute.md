# Stage 3 combined: local, estate and cloud compute

**Your place in the roadmap:** [Choose a compute path](11-compute-roadmap.md). Start after private inference and each approved cloud backend work independently. For a shared MaluOS GPU, finish [GPU setup](11-gpu-server.md) and [estate enrolment](13-estate.md), then [cloud setup](11-cloud-models.md), before following this guide. Same-host private inference does not require estate enrolment.

A hybrid deployment combines privately operated models with one or more
cloud API hosts. Applications ask the MaluOS gateway for a task-oriented
tier; its routing policy selects eligible backends. Private capacity can
serve routine work, approved cloud models can supply additional capacity
or capabilities, and private-only callers can be prohibited from cloud use.

Use [the GPU-server guide](11-gpu-server.md) to prepare private compute,
[estate enrolment](13-estate.md) to share it, and [cloud models](11-cloud-models.md)
to configure cloud accounts. This guide joins those paths at the gateway.
Apple Silicon and DGX Spark preparation is covered in
[ARM inference](11-arm-inference.md). Their standalone node integration
must pass its readiness checks before using those hosts in a hybrid route;
installing Ollama alone does not create an estate backend.

**Machine:** the office, desktop or other host originating the workload.
**Exit criterion:** private-only work stays on permitted private backends;
cloud-enabled work follows its approved route, including tested fallback,
and the ledger identifies the actual backend and model.

Source baseline: MaluOS main `76b4fee896e46e1ea700f441422474a5ab00e1a3`,
reviewed November 9, 2026. These are source-derived instructions; the
combined deployment and failure scenarios still require validation on
the organization's selected hardware, accounts and applications.

## 0. Define which work may use which compute

| Workload | Routing intent | Control |
|---|---|---|
| Must stay on the calling host | Same-host model only | Backend allowlist for `ollama-local`, cloud off, remote off |
| May use the organization's other servers | Same-host and authorized estate models | Cloud off; remote on; egress/classification ceilings appropriate to that private traffic |
| May use approved cloud hosts | Private models first, approved cloud alternatives | Cloud on; explicit cloud credentials, backend allowlist, ordered route and egress ceiling |
| Needs a particular cloud model | A separate cloud tier | Model capability and caller policy determine the allowed hosts |

Use separate caller identities/policies where workloads have different
requirements. A default policy is not an immutable organization-wide
ceiling: the gateway merges default, scope and principal settings, with
later non-null values replacing earlier ones. Review the effective caller
policy and test it rather than relying on a default alone.

Sensitivity labels are supplied by the caller; they do not classify prompt
contents. Policies affect gateway calls, not applications making direct
provider requests. A single caller's egress ceiling also applies to
private remote backends, not just cloud backends. Separate identities and
backend allowlists are useful when those boundaries differ.

## 1. Verify the two compute paths independently

On the **calling host**:

```bash
maluctl gateway whoami
maluctl gateway status
sudo maluctl gateway catalog
maluctl gateway estate
```

Before combining routes, prove a request to the private model and each
cloud model independently using the preceding guides. A local GPU is not
required on the office if an enrolled estate GPU serves it.

For estate compute, finish stage 4 enrolment first. The directory publishes
eligible GPU hosts and their model names to the caller's gateway. Use
`maluctl gateway estate refresh` after changes and record the actual
backend identifiers shown. Do not invent `estate:…` names from hostnames.

Cloud credentials belong on this calling host. An incoming estate request
cannot spend the serving GPU host's cloud credit. The intended hybrid path
is: the caller tries private compute, then the caller's own gateway can
select an approved cloud host. It is not a chain in which a remote GPU
silently sends the request to its cloud account.

## 2. Build a tier with a private model and cloud alternatives

The examples use `user:maluos`, `cloud-a` and `cloud-b` from the cloud
guide. Substitute the actual caller and backends. Review and record the
existing policy first; the examples change that principal's routing.

In a Bash terminal on the **calling host**:

```bash
read -r -p 'Exact private model name, as reported by the gateway: ' PRIVATE_MODEL
read -r -p 'Model ID tested on cloud-a: ' MODEL_A
read -r -p 'Model ID tested on cloud-b: ' MODEL_B
sudo maluctl gateway tier add hybrid-chat --description 'Private compute with approved cloud alternatives'
sudo maluctl gateway alias set hybrid-private --tier hybrid-chat \
  --backend ollama-local --model "$PRIVATE_MODEL" --position 0
sudo maluctl gateway alias set hybrid-cloud-a --tier hybrid-chat \
  --backend cloud-a --model "$MODEL_A" --position 10
sudo maluctl gateway alias set hybrid-cloud-b --tier hybrid-chat \
  --backend cloud-b --model "$MODEL_B" --position 20
```

The seeded `ollama-local` backend must exist. If serving the model on this
host, install and pull it as in the GPU guide. If serving it only on the
estate, the alias still supplies the private model name for tier matching;
it does not install that model on the caller.

**Estate behavior matters:** the gateway automatically adds estate rungs
when they advertise a model named by a tier alias. Those rungs are appended
after the catalogue's explicit candidates. With explicit cloud aliases,
that can put cloud before estate unless the policy ladder corrects the
order. Estate backends are dynamic; the current database foreign key does
not allow creating a persistent alias directly against an estate rung.

## 3. Order private and cloud backends explicitly

For same-host compute followed by cloud:

```bash
APPROVED_BACKENDS=ollama-local,cloud-a,cloud-b
```

If using estate GPUs, instead enter a comma-separated list of the exact
eligible estate backend names from `maluctl gateway estate`, without spaces:

```bash
read -r -p 'Approved estate backend names, comma-separated: ' ESTATE_BACKENDS
APPROVED_BACKENDS="ollama-local,$ESTATE_BACKENDS,cloud-a,cloud-b"
```

Do not run the estate variant with an empty list. Include all approved
estate nodes you want eligible; update this list when nodes change. The
gateway can rank estate nodes among themselves by estate priority and
expected wait, so the list does not guarantee a particular GPU node.

Create a workload-specific class and apply the policy:

```bash
sudo maluctl gateway class set hybrid-work --priority 1 \
  --max-queue 100 --max-wait 120 --fallback-wait none
sudo maluctl gateway policy set --principal user:maluos \
  --class hybrid-work --tiers hybrid-chat --backends "$APPROVED_BACKENDS" \
  --ladder "$APPROVED_BACKENDS" --cloud yes --remote yes --egress public
maluctl gateway chat 'Reply with a short greeting.' \
  --model hybrid-chat --sensitivity public
maluctl gateway routes --limit 5
```

This example permits only public-classified requests to leave the host.
It is useful for the first synthetic test, not a blanket authorization
to send business records to a cloud provider. The cloud secret grants and
prices from the cloud guide must exist for this caller on this host.

With `fallback-wait none`, a healthy private candidate is not skipped
merely because its estimated wait exceeds a cloud-fallback threshold.
Queue limits and errors can still reject requests; this is not an
unlimited wait or a guarantee that every queue rejection falls through.

To permit cloud overflow when estimated private wait is high, set a
threshold for this class, for example:

```bash
sudo maluctl gateway class set hybrid-work --fallback-wait 20
```

The gateway can then skip eligible non-cloud candidates whose estimated
wait exceeds 20 seconds when an eligible cloud alternative exists.
This is a prediction-based routing decision, not a timer that starts a
second provider request after waiting 20 seconds. Choose and test the
threshold for the workload.

## 4. Establish the private-only policy

For a workload that must never use cloud accounts, apply the policy to
its actual principal. The example below changes `user:maluos` from the
hybrid test to private-only; in production use the identity designated
for private work.

With estate compute:

```bash
PRIVATE_BACKENDS="ollama-local,$ESTATE_BACKENDS"
sudo maluctl gateway policy set --principal user:maluos \
  --class hybrid-work --tiers hybrid-chat --backends "$PRIVATE_BACKENDS" \
  --ladder "$PRIVATE_BACKENDS" --cloud no --remote yes --egress internal
maluctl gateway chat 'Synthetic private-route test.' \
  --model hybrid-chat --sensitivity internal
maluctl gateway routes --limit 5
```

The estate nodes must also permit the classification. For a workload that
must stay on the same host, use this alternative:

```bash
sudo maluctl gateway policy set --principal user:maluos \
  --backends ollama-local --ladder ollama-local --cloud no --remote no
```

If private compute becomes unavailable, these policies should produce a
failure rather than a cloud call. Do not widen the policy just to make
that test return a response. Restore the cloud-enabled policy from step 3
only for a caller whose work is authorized for that behavior.

## 5. Understand fallback and preference hints

| Mechanism | Current behavior |
|---|---|
| Tier aliases and policy ladder | Define candidates and order; policy and credential checks remove ineligible candidates |
| `--prefer cloud` | Skips non-cloud candidates when an eligible cloud candidate exists |
| `--prefer local` | Can filter cloud candidates when eligible non-cloud candidates remain; “local” includes remote private backends in this logic |
| `--prefer estate` | Filters to eligible estate candidates when they exist; not a promise of subsequent cloud fallback |
| Backend errors | Certain errors, including unavailable backend, rate limit, credential, model and capability errors, can advance to another eligible rung |
| Streaming interruption | Fallback can happen before the first chunk is returned; there is no seamless cross-provider continuation once output has begun |

Preference hints do not replace policy. `--prefer local` is not a
private-only guarantee: earlier eligibility and wait rules can leave only
cloud candidates. Use `--cloud no` and backend/remote restrictions for the
required boundary. An application can also send `X-MaluOS-Local-Only: 1`
to narrow a request to the same host; that excludes estate compute too.

Fallback changes the model, not merely the hardware. Validate task quality,
tools, structured output and context limits across every alternative.
Separate embedding workflows from chat fallbacks unless the memory system
explicitly supports the selected embedding models and index transition.

## 6. Observe costs and test failure scenarios

```bash
sudo maluctl gateway usage --since 1h --by backend
sudo maluctl gateway usage --since 1h --by principal
maluctl gateway routes --limit 20
sudo maluctl gateway alerts --since 1h
```

Record the intended route and compare it with the selected backend, skipped
candidates, tokens and cost. The current budget check uses the initially
selected backend's price estimate; the execution fallback loop does not
repeat that budget check for each later backend. A local-first request
without a configured price estimate can therefore reach a priced cloud
fallback without the same estimate gate. Use cloud-account spending
limits and observe fallback charges; do not advertise gateway budgets as
a hard hybrid-spend ceiling.

Run these with synthetic data on a test setup or in an agreed maintenance
window. Disabling a backend affects other callers on that gateway. Estate
availability should be changed on a test GPU node or through its sharing
policy, not by trying to disable an ephemeral estate backend as a database
row. Restore the original availability and policies after each test.

| Test | Expected result |
|---|---|
| Private healthy, cloud allowed | Selected private model and ledger row, using the intended order |
| Private unavailable, cloud allowed | Approved cloud alternative answers; route records the unavailable/skipped private path |
| Primary cloud unavailable | Next approved cloud host answers if its credentials, policy and capabilities permit |
| All private compute unavailable, cloud prohibited | Request fails; no cloud backend is used |
| Private wait exceeds the configured threshold | Cloud may be selected for a cloud-enabled caller; inspect the wait-related reason |
| Request exceeds egress ceiling | Remote/cloud candidates are rejected as applicable; private-only processing or failure |
| Provider streams then disconnects | Client receives an interruption; no claim of seamless model continuation |
| Internet unavailable | Private-capable work still answers; cloud-only work fails clearly |

“Internet unavailable” here tests the model route. It does not prove that
an application using cloud authentication, tools, retrieval or other
services is entirely offline-capable.

## Done when

- The real application/agent uses the intended gateway identity and tier.
- Private-only policy holds even during failures; approved cloud fallback
  works across the selected hosts.
- Estate roles, secret grants, endpoint/model inventory, classifications
  and operator-entered prices are recorded on each calling host.
- Routes and usage explain which backend handled the work; costs and
  capability differences are understood.
- The failure tests have been run and the production policy restored.

Continue with [applications](12-applications.md) and [desks](14-desks.md)
as appropriate. The GPU, cloud and hybrid guides are compute choices;
estate enrolment is still required wherever private nodes or desks share
resources.

## Source references

Reviewed source: [candidate selection and policy merging](https://github.com/maludb/maluos/blob/76b4fee896e46e1ea700f441422474a5ab00e1a3/packages/maluos-gateway/lib/maluos_gateway/db.py),
[routing, fallback and budgeting](https://github.com/maludb/maluos/blob/76b4fee896e46e1ea700f441422474a5ab00e1a3/packages/maluos-gateway/lib/maluos_gateway/server.py),
[estate integration](https://github.com/maludb/maluos/blob/76b4fee896e46e1ea700f441422474a5ab00e1a3/packages/maluos-gateway/lib/maluos_gateway/estate.py),
[CLI](https://github.com/maludb/maluos/blob/76b4fee896e46e1ea700f441422474a5ab00e1a3/packages/maluos-gateway/lib/maluctl.d/gateway.py).

