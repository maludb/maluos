# DGX Spark: prepare a private inference host

**Your place in the roadmap:** [Choose a compute path](11-compute-roadmap.md). Start with [ARM inference](11-arm-inference.md) sections 1–2. Follow this guide, use ARM section 3 when directed for the office connection test, then finish the reboot checks here. Return to ARM sections 4–5 to record readiness; production integration remains pending.

Keep the Spark's NVIDIA DGX OS and NVIDIA-managed driver stack. Its ARM64
CPU architecture is separate from its NVIDIA GB10 GPU; do not use the
MaluOS AMD64 ISO or the x86 GPU-server package instructions on this host.
Ollama's [hardware list](https://docs.ollama.com/gpu) includes GB10.

**Status:** this installs native Ollama and prepares the host. The
[`maluos-local-llm-server` integration is unfinished](11-arm-inference.md);
the reviewed repository has no runnable node service or Linux installer.
No physical DGX Spark validation was performed for this guide.

## 1. Finish DGX setup and updates

Complete NVIDIA's [first-boot setup](https://docs.nvidia.com/dgx/dgx-spark/first-boot.html)
locally or through its network setup flow. Configure the administrator,
network access and a stable private address/name. Use the **DGX Dashboard**
for OS, driver and firmware updates on a Founders Edition; use the hardware
vendor's process for other editions. Reboot if required before continuing.
[NVIDIA update guide](https://docs.nvidia.com/dgx/dgx-spark/os-and-component-update.html).

On the **Spark**:

```bash
uname -m
cat /etc/os-release
nvidia-smi
free -h
df -h /usr/share /var
```

Expect `aarch64` and a working NVIDIA driver. Record the OS and driver
versions. If `nvidia-smi` fails, repair the vendor stack before installing
inference software; the MaluOS `maluos-nvidia` package is not the remedy.
Plan model/context capacity using actual available shared memory, not
only a discrete-card VRAM assumption.

Verify SSH access from the office using the account configured during
setup and the host's private/VPN address. This is the management path for
the later network proof.

## 2. Install native ARM64 Ollama

The official Linux installer detects architecture. Download it to a file
for review, then run it on the Spark; it may use sudo to install files
and create its `ollama` service. Record the selected version and preserve
the installer used. If Ollama is already installed, inspect that service
before upgrading or creating a second listener.

```bash
curl --fail --location --show-error https://ollama.com/install.sh -o ollama-install.sh
less ollama-install.sh
sh ollama-install.sh
ollama --version
systemctl status ollama --no-pager
```

For a version-controlled rollout, use the installer's `OLLAMA_VERSION`
setting with a version verified for the Spark. Select ARM64 when using
manual archives. Do not substitute an AMD64 archive.
[Ollama Linux installation](https://docs.ollama.com/linux).

## 3. Configure the service for a local-only test

On the **Spark**, run:

```bash
sudo systemctl edit ollama.service
```

Add these entries to the override, merging any existing settings:

```ini
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11434"
Environment="OLLAMA_NO_CLOUD=1"
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
```

Then apply and check:

```bash
sudo systemctl daemon-reload
sudo systemctl enable ollama.service
sudo systemctl restart ollama.service
systemctl status ollama.service --no-pager
sudo journalctl -u ollama.service -n 80 --no-pager
ss -ltn '( sport = :11434 )'
curl --fail --silent --show-error http://127.0.0.1:11434/api/version
```

Expect loopback-only listening, a version response and the log entry
`Ollama cloud disabled: true`. One loaded model and one parallel request
are starting values for validation, not a permanent Spark capacity limit.
[Service environment and cloud controls](https://docs.ollama.com/faq).

## 4. Pull a model and verify acceleration

Start with the small [qwen3:0.6b](https://ollama.com/library/qwen3:0.6b)
validation model before testing production weights and context lengths:

```bash
ollama pull qwen3:0.6b
ollama list
curl --fail --silent --show-error http://127.0.0.1:11434/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3:0.6b","messages":[{"role":"user","content":"Say hello in five words."}],"think":false,"stream":false,"keep_alive":"5m"}'
ollama ps
nvidia-smi
```

Check GPU placement in `ollama ps` and runtime logs; a successful HTTP
answer alone can hide CPU fallback. While a longer inference runs, inspect
GPU activity from another terminal. Record the runtime/model versions,
memory pressure and observed throughput. Use NVIDIA's driver/update path
if the GPU is unavailable and verify that the Ollama build supports GB10.

## 5. Check the network and reboot recovery

Run the [office-to-host SSH inference proof](11-arm-inference.md#3-prove-inference-from-the-office-over-ssh).
This needs SSH connectivity, not an open public port 11434 or 11435.

During an agreed maintenance window, reboot and repeat the local API,
GPU-placement and SSH-forwarded checks. Confirm `ollama.service` starts
automatically with the same loopback/cloud settings. Record its model
storage location and service ownership before relocating models or
planning backups. Keep one owner for the inference service.

**Done for preparation:** native ARM64 runtime, GPU execution, local-only
configuration, private network proof and restart recovery are verified.
Next is the [node-service implementation and registration gate](11-arm-inference.md#4-complete-the-node-service-before-production-registration).

