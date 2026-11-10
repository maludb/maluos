# Stage 3 alternative: add compute through cloud model APIs

**Your place in the roadmap:** [Choose a compute path](11-compute-roadmap.md). Follow this guide on each calling MaluOS host. Repeat provider setup for each API host/account. Cloud-only use needs no GPU node. For hybrid use, prove private compute through [GPU setup](11-gpu-server.md) and [estate enrolment](13-estate.md), then combine the working routes in [hybrid compute](11-hybrid-compute.md).

An organization can add model capacity without installing a GPU server.
Configure one or more cloud API hosts as named backends in the MaluOS
inference gateway, give authorized callers access to their credentials,
and select the models through aliases or tiers. Repeat the process for
each host, account or region the organization chooses to use.

The catalogue is not limited to one cloud provider. Each backend has its
own name, API endpoint, secret reference, models and concurrency setting.
The usable number depends on gateway resources, provider quotas and the
organization's operating requirements. Compatibility depends on the API
protocol, not simply on a host describing itself as an AI provider.

For owned hardware, use [the GPU-server guide](11-gpu-server.md). For
local compute with cloud fallback, use [hybrid compute](11-hybrid-compute.md).

**Machine:** the office or other MaluOS host whose gateway receives the
workload. **Exit criterion:** each selected provider answers an authorized
test through that gateway, the route is visible, and the intended callers
have appropriate policy and credential grants.

Source baseline: MaluOS main `76b4fee896e46e1ea700f441422474a5ab00e1a3`,
reviewed November 9, 2026. The examples are derived from source; no paid API
calls or live cloud deployment were performed while writing this guide.

## 0. Decide where the calls will run

Configure the gateway on the host that originates the model request. For
an office workload that is the office; for a desktop tool using its own
gateway it is the desktop. A gateway catalogue and vault are local to
that installation. Repeat the configuration on other calling hosts as
needed, with their own grants and account choices.

Joining the estate does not distribute cloud keys or cloud credits. The
serving gateway explicitly refuses cloud spending for incoming estate
peer calls. Estate sharing discovers private compute; it is not a shared
cloud billing service.

Also distinguish these two existing configuration paths:

| Path | What it configures |
|---|---|
| `maluctl office-setup providers …` | Provider credentials in the Business OS agent runner's environment, or mail settings; see [office configuration](10-office-configuration.md) |
| `maluctl secret …` and `maluctl gateway …` | Gateway credentials in the vault, backend catalogue, model routing, policy and gateway usage |

Setting a runner key does not create a gateway backend or vault grant.
Gateway policy governs requests that go through the gateway. An application
that calls a provider directly needs its own configuration and controls.
As part of adoption, verify which path each application or agent uses.

## 1. Record each host and check protocol support

For every host/account, record: backend name, protocol kind, endpoint,
model identifiers, credential owner, approved callers, permitted data,
account quotas and prices. Use a separate backend name when accounts,
regions, billing or access requirements differ, even at the same provider.

| Gateway kind | API contract | Endpoint convention |
|---|---|---|
| `anthropic` | Anthropic Messages with `x-api-key` | Adapter appends `/v1/messages` to the configured root |
| `openai` | OpenAI Chat Completions and embeddings with bearer authentication | Adapter appends `/v1/chat/completions` or `/v1/embeddings` |
| `openai_compat` | Another host implementing that compatible API and authentication | Supply the prefix before `/v1/chat/completions`; verify its actual paths |
| `ollama_cloud` | Ollama's native API with bearer authentication | Supply the root for native `/api/…` paths |

For example, a host documenting `https://models.vendor.example/api/v1/chat/completions`
needs `https://models.vendor.example/api` as the configured endpoint. Do
not copy a client SDK's `/v1` base URL blindly: that would produce
`/v1/v1/chat/completions` with the current adapter.

These adapters do not promise support for arbitrary vendor APIs, signed
cloud-platform authentication, deployment-specific URLs or every new model
feature. A Responses-only endpoint is not a Chat Completions endpoint.
Confirm tools, streaming, structured output, images, embeddings and context
limits for the exact model and operation you intend to use. Anthropic's
gateway adapter does not implement embeddings.

Choose current model IDs and API roots from the host's own documentation
and account console. This guide intentionally does not pin a changing
commercial model catalogue or price list. Record the provider's data
handling and regional terms separately from protocol compatibility.

## 2. Check the gateway and caller identity

On the **calling host**, as the user who will make the test calls:

```bash
maluctl gateway status
maluctl gateway whoami
maluctl secret whoami
sudo maluctl gateway catalog
```

The gateway and vault must be available and the caller enrolled. Cloud
credential lookup requires an enrolled principal. If it reports
`not_enrolled`, correct that host's identity/provisioning before continuing.

The examples below use `user:maluos`. Replace that reference with the
principal reported for the actual caller. Run test chats as that user,
without `sudo`; a root test does not prove the user's grants. Review and
record existing policy before changing it: the examples set the test
principal's routing fields and must be adapted for an existing workload.

## 3. Add the first host and its credential

In a Bash terminal on the **calling host**, set these non-secret values
from the host's documentation. The sample names can be changed:

```bash
BACKEND=cloud-a
KIND=openai_compat
read -r -p 'API root before /v1/chat/completions: ' ENDPOINT
read -r -p 'Exact provider model ID: ' MODEL
```

Use `anthropic`, `openai` or `ollama_cloud` when that is the intended
protocol, and supply its root as described above.

Store the account key in the shared vault compartment, then grant only
the test caller permission to use it:

```bash
sudo maluctl secret add "system/$BACKEND" --kind api_key --provider "$KIND"
# enter the secret at the hidden prompt in your own terminal
sudo maluctl secret grant "system/$BACKEND" --to user:maluos --level use
sudo maluctl secret info "system/$BACKEND"
```

For an existing secret, inspect its metadata and use `maluctl secret rotate`
when changing the value; do not add it again. Do not paste keys into chat,
the documentation or backend command arguments. `use` permits the gateway
to use the credential for the caller; it does not grant the caller `read`.

Register the backend and give its model an unambiguous test alias:

```bash
sudo maluctl gateway backend add "$BACKEND" --kind "$KIND" \
  --endpoint "$ENDPOINT" --secret "system/$BACKEND" \
  --models "$MODEL" --max-concurrent 2
sudo maluctl gateway alias set "$BACKEND-chat" --backend "$BACKEND" --model "$MODEL"
```

`2` is a conservative example of gateway concurrency, not a provider quota.
Adjust it for the account and workload. Reusing a backend name updates its
configuration and enables it; use a new name when adding a distinct host.
Repeat aliases for additional models, using unique caller-visible names.

## 4. Allow and test that host

For a test containing public information only:

```bash
sudo maluctl gateway policy set --principal user:maluos \
  --cloud yes --egress public --backends "$BACKEND" --ladder none
maluctl gateway chat 'Reply with a short greeting.' \
  --model "$BACKEND-chat" --sensitivity public
maluctl gateway routes --limit 5
sudo maluctl gateway usage --since 10m --by backend
```

Expect the configured backend and concrete model in the route, and a
successful ledger entry. Backend registration or a health indicator alone
does not prove that a credential and model work together.

Sensitivity is a request classification, not automatic inspection of its
contents. The gateway defaults an unlabelled request to `internal`; with
the example `public` egress ceiling it will refuse cloud egress. Assign
classifications honestly and set the caller's policy for the intended data.

## 5. Add as many hosts as the organization needs

Repeat steps 3–4 with `BACKEND=cloud-b`, then `cloud-c`, and so on. Each
can use a different protocol, provider, account, region and model. Test
each independently before adding it to a shared route. Keep the actual
model identifiers in your deployment record; shell variables from an
earlier terminal are not persistent configuration.

For a two-host example, substitute the model IDs already tested:

```bash
read -r -p 'Model ID tested on cloud-a: ' MODEL_A
read -r -p 'Model ID tested on cloud-b: ' MODEL_B
sudo maluctl gateway tier add cloud-chat --description 'Approved cloud conversation models'
sudo maluctl gateway alias set cloud-primary --tier cloud-chat \
  --backend cloud-a --model "$MODEL_A" --position 0
sudo maluctl gateway alias set cloud-secondary --tier cloud-chat \
  --backend cloud-b --model "$MODEL_B" --position 10
sudo maluctl gateway policy set --principal user:maluos \
  --cloud yes --egress public --tiers cloud-chat \
  --backends cloud-a,cloud-b --ladder cloud-a,cloud-b
maluctl gateway chat 'Reply with a short greeting.' --model cloud-chat --sensitivity public
```

The alias positions establish an order; a policy ladder can reorder and
restrict candidate backends. Add further hosts by repeating the backend,
secret/grant and alias steps, then extending this principal's backend
allowlist and ladder. A backend omitted from either list is not a fallback
for that principal. Inspect `maluctl gateway catalog` after each change.

The tier is for interchangeable tasks, not a guarantee that models have
equal capabilities. Keep separate tiers for tasks such as conversation,
coding and embeddings when their requirements differ. In particular,
switching embedding models can change dimensions and vector meaning;
configure the memory system and any required re-indexing separately.

## 6. Configure prices, spending and other callers

The gateway uses operator-entered prices; it does not fetch current vendor
tariffs. For each model, enter the account's prices per million tokens:

```bash
read -r -p 'Input price per million tokens, USD: ' INPUT_RATE
read -r -p 'Output price per million tokens, USD: ' OUTPUT_RATE
read -r -p 'Cached-input price per million tokens, USD: ' CACHED_RATE
sudo maluctl gateway price set cloud-a "$MODEL_A" \
  --input "$INPUT_RATE" --output "$OUTPUT_RATE" --cached "$CACHED_RATE" --currency USD
sudo maluctl gateway price list
sudo maluctl gateway policy set --principal user:maluos \
  --budget usd_per_day=5,usd_per_month=100
```

Repeat pricing for every cloud model and replace the example budget with
the approved allowance. These are gateway accounting controls, not a
guaranteed provider bill cap: missing prices skip the estimate-based
budget check, and estimates, concurrent work and fallback can differ from
final charges. Use the provider account's spending controls as well.

For each additional user, application or agent, confirm its gateway
principal, grant the appropriate vault secrets and set its policy. Do not
assume an agent inherits the operator's key. Use the actual identity
reported by the calling application; a Business OS application user and
a Linux gateway principal are not automatically the same identity.

Monitor:

```bash
sudo maluctl gateway usage --since 7d --by backend
sudo maluctl gateway usage --since 7d --by principal
sudo maluctl gateway alerts --since 7d
```

## 7. Prove failover and connect the real workload

On a test gateway, temporarily disable `cloud-a`, call `cloud-chat`, inspect
the route and re-enable the backend. Disabling a backend affects every
caller using that gateway; schedule this test if it already serves users.

```bash
sudo maluctl gateway backend disable cloud-a
maluctl gateway chat 'Reply with a short greeting.' --model cloud-chat --sensitivity public
maluctl gateway routes --limit 5
sudo maluctl gateway backend enable cloud-a
```

Expect `cloud-b`. Re-enable the primary even if the test fails. Repeat
with the additional approved fallbacks. Also test a restricted request
against this public-only policy: it should fail without a cloud call.

```bash
maluctl gateway chat 'Synthetic policy test; contains no private data.' \
  --model cloud-chat --sensitivity restricted
```

Finally configure the actual client to use this gateway, its authenticated
identity and the chosen tier. The local Unix socket is
`/run/maluos/gateway.sock`; the gateway serves compatible OpenAI and Ollama
interfaces. TCP clients need a separately configured listener and gateway
credential. Provider keys remain in the vault. Prove the real application's
request appears in gateway usage; CLI success alone does not connect it.

**Done when:** each host/model passes its individual test, the combined
route and policy denial behave as intended, prices and grants are recorded,
and the real caller appears in the ledger. Cloud-only compute does not
require a GPU-node join. Continue to [hybrid compute](11-hybrid-compute.md)
when adding private capacity, or to the application's own integration checks.

## Source references

Reviewed source: [CLI](https://github.com/maludb/maluos/blob/76b4fee896e46e1ea700f441422474a5ab00e1a3/packages/maluos-gateway/lib/maluctl.d/gateway.py),
[adapters](https://github.com/maludb/maluos/blob/76b4fee896e46e1ea700f441422474a5ab00e1a3/packages/maluos-gateway/lib/maluos_gateway/cloud.py),
[routing and budgets](https://github.com/maludb/maluos/blob/76b4fee896e46e1ea700f441422474a5ab00e1a3/packages/maluos-gateway/lib/maluos_gateway/server.py),
[vault CLI](https://github.com/maludb/maluos/blob/76b4fee896e46e1ea700f441422474a5ab00e1a3/packages/maluos-vault/lib/maluctl.d/secret.py).

