# Stage 3: choose and connect compute

Start here for the `11-` compute guides. Choose the path that matches your
hardware and where your organization permits model requests to run. You do
not need to follow every guide or buy a GPU to use cloud models.

This roadmap organizes the existing procedures as of November 10, 2026.
Each linked guide retains its source baseline and validation limits; this
roadmap does not mark an untested deployment or unfinished integration complete.

## Before you start

Complete [office configuration](10-office-configuration.md) and identify the
application or agent that will use the models. Hardware preparation may run
alongside office setup, but connecting it to the office requires a working
office and management access to the selected hosts.

Record where the request originates: the office, a desktop, or another
MaluOS host. Configure cloud credentials and routing on that calling host.
Decide which workloads must remain private and which may use approved cloud
providers. Office-setup provider keys and gateway credentials are separate;
follow the selected guide for the path your application actually uses.

## Choose your path

| What you want | Follow these documents in order | Completion point |
|---|---|---|
| Private compute on a MaluOS NVIDIA GPU server | [GPU server](11-gpu-server.md) → [estate enrolment](13-estate.md) | The calling host reaches the GPU through the estate and usage identifies the serving node |
| Another GPU server in a Proxmox VM | [GPU VM branch](11-gpu-server.md#a-second-gpu-node-a-vm-on-proxmox-with-the-card-passed-through-no-static-address) → [estate checks](13-estate.md) | The additional node and its models are reachable, not merely listed |
| Cloud models, without a private GPU server | [Cloud models](11-cloud-models.md) | Every selected host/model and the real application's gateway route pass their checks |
| Private models plus cloud models | [GPU server](11-gpu-server.md) → [estate enrolment](13-estate.md) → [cloud models](11-cloud-models.md) → [hybrid compute](11-hybrid-compute.md) | Private-only restrictions and approved fallback pass the hybrid failure tests |
| Private compute on an Apple Silicon Mac | [ARM overview](11-arm-inference.md) → [Mac preparation](11-gpu-macos.md) → ARM readiness review | Host preparation only; production node integration remains pending in the reviewed source |
| Private compute on DGX Spark | [ARM overview](11-arm-inference.md) → [Spark preparation](11-gpu-dgx-spark.md) → ARM readiness review | Host preparation only; production node integration remains pending in the reviewed source |

Multiple cloud hosts repeat the provider setup in the cloud guide. Multiple
private servers repeat host preparation and enrolment. Neither requires a
separate office installation for each compute provider.

## Path A: a MaluOS GPU server

1. Follow [GPU server](11-gpu-server.md) sections 1–5, including the local
   model test. For a fresh installation, follow its current-image guidance;
   the old-office cleanup in section 3 applies only if an office was provisioned
   on that GPU host. Use the separate VM branch for a passed-through GPU.
2. Skip section 6's optional manual LAN pairing for the normal estate path.
3. Complete [estate enrolment](13-estate.md): establish the office hub, join
   the inference node, verify the overlay, expose the gateway on that overlay
   and prove a request from the calling host.
4. For private-only operation, connect and test the real application. For a
   hybrid deployment, continue with Path C below.

A successful chat on the GPU server proves local inference. It does not yet
prove the office or a desktop can use that server. The estate checks establish
that second milestone. Although the estate guide is numbered `13-`, it comes
before hybrid routing when the private model runs on another estate host.

## Path B: cloud models only

1. Follow [cloud models](11-cloud-models.md) on the calling MaluOS host.
2. Configure and test the first provider, then repeat for each additional
   host, account or region. Record credentials, grants, permitted models and
   prices as the guide specifies.
3. Test routing, policy denial and any chosen fallback. Connect the actual
   application and verify its requests appear in gateway usage.

No GPU installation or inference-node enrolment is required for this path.
Estate membership does not distribute cloud keys or credits. Desktops that
need other estate services still follow their own enrolment process.

## Path C: private and cloud models together

1. Complete Path A through a successful remote private-model request, and
   Path B through a successful request to each approved cloud backend. If
   both paths already work, start at the next step.
2. Follow [hybrid compute](11-hybrid-compute.md) on the calling host to set
   tiers, backend order and separate private-only and cloud-enabled policies.
3. Run its failure scenarios, including private-node loss, cloud failure and
   Internet loss. Verify private-only work cannot fall back to the cloud.
4. Restore the intended production configuration and verify the real caller's
   identity, route and usage.

If the private model runs on the calling MaluOS host itself, estate enrolment
is not needed for that local route. It is needed when using shared estate
GPUs. ARM host preparation alone does not qualify as a working private route.

## Path D: Apple Silicon or DGX Spark preparation

1. Read [ARM inference](11-arm-inference.md) through sections 1–2 for network
   placement and the current integration boundary.
2. Follow either [Mac preparation](11-gpu-macos.md) or
   [Spark preparation](11-gpu-dgx-spark.md). Keep the vendor operating system.
3. When the hardware guide asks for the office connection test, follow
   [ARM section 3](11-arm-inference.md#3-prove-inference-from-the-office-over-ssh),
   then return to the hardware guide for its restart/lifecycle checks.
4. Review [ARM sections 4–5](11-arm-inference.md#4-complete-the-node-service-before-production-registration)
   and record the host as prepared, with MaluOS integration pending. Those
   sections describe remaining implementation and acceptance requirements,
   not additional installation commands for the operator.

Stop at host preparation with the reviewed version. Do not run the MaluOS
ISO, x86 driver instructions or MaluOS estate-join commands on these ARM
hosts. Continue to production registration or hybrid use only when a runnable
node service and verified integration instructions are available.

## Finish and continue

For an operational compute path, record the host/provider and model inventory,
the caller identity, allowed data, working route and observed usage. Run a real
application request as well as the guide's synthetic tests. For ARM preparation,
record its narrower completion milestone and the outstanding integration work.

Return to [applications](12-applications.md) for any applications not yet
installed, then [desks](14-desks.md) for desktop setup and its estate requirements.
Use the [end-to-end roadmap](01-roadmap.md) to track the wider network rollout.
When adding capacity later, return to the path selection above and repeat only
the relevant host/provider steps and their acceptance checks.

