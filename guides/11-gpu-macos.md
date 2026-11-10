# Apple Silicon Mac: prepare a private inference host

**Your place in the roadmap:** [Choose a compute path](11-compute-roadmap.md). Start with [ARM inference](11-arm-inference.md) sections 1–2. Follow this guide, use ARM section 3 when directed for the office connection test, then finish the lifecycle checks here. Return to ARM sections 4–5 to record readiness; production integration remains pending.

Use this path for an M-series Mac that keeps macOS. It is distinct from
the Intel Mac installation in [desks](14-desks.md). The GPU is Apple's
integrated GPU, accessed through Metal. Ollama documents macOS 14 Sonoma
or newer and Apple M-series CPU/GPU support.
[macOS requirements and installation](https://docs.ollama.com/macos),
[Metal support](https://docs.ollama.com/gpu#metal-apple-gpus).

**Status:** this installs Ollama and prepares the host. The
[`maluos-local-llm-server` integration is unfinished](11-arm-inference.md);
there is no working `sllm` installer or packaged macOS service in the
reviewed repository. No Mac GPU installation was performed for this guide.

## 1. Check the Mac and management access

On the **Mac**, in Terminal:

```bash
uname -m
sw_vers
system_profiler SPHardwareDataType SPDisplaysDataType
df -h "$HOME"
```

Expect `arm64` from a native terminal and an Apple chip/GPU in the hardware
report. Record memory and free disk space. Use a persistent host name or
DHCP reservation. Configure power/sleep behavior for the intended serving
hours; a sleeping laptop cannot provide dependable shared capacity.

For the later private network test, enable **System Settings → General →
Sharing → Remote Login**, restricted to the intended operator account.
Set up SSH key access and check it from the office.
[Apple Remote Login instructions](https://support.apple.com/en-au/guide/mac-help/mchlp1066/27/mac/27).

## 2. Install native Ollama

Download the macOS installer from [Ollama](https://ollama.com/download/mac),
move the app to Applications and launch it. Allow its CLI setup when
prompted. Use the native application for Metal acceleration; Docker
Desktop on macOS does not provide GPU passthrough for Ollama.
[Ollama's GPU/container guidance](https://docs.ollama.com/faq#how-do-i-use-ollama-with-gpu-acceleration-in-docker).

Quit Ollama from its menu before setting the service environment. In
Terminal as the user who runs the app:

```bash
launchctl setenv OLLAMA_HOST '127.0.0.1:11434'
launchctl setenv OLLAMA_NO_CLOUD '1'
launchctl setenv OLLAMA_NUM_PARALLEL '1'
launchctl setenv OLLAMA_MAX_LOADED_MODELS '1'
open -a Ollama
```

These settings establish a loopback-only, local-model validation setup.
They must reach the running app, so restarting it is necessary.
`launchctl setenv` is not persistent configuration across reboot/login;
repeat it before launching Ollama in a new session. A persistent launchd
configuration and unattended startup/recovery remain deployment work.
[Ollama environment configuration](https://docs.ollama.com/faq#setting-environment-variables-on-mac).

Check the runtime:

```bash
ollama --version
curl --fail --silent --show-error http://127.0.0.1:11434/api/version
lsof -nP -iTCP:11434 -sTCP:LISTEN
```

Expect a version response and a loopback listener, not `*:11434`.
Inspect `~/.ollama/logs/server.log` if it fails. Confirm the log says
`Ollama cloud disabled: true`; keep cloud disabled for this private node.

## 3. Load a model and prove GPU execution

Use [qwen3:0.6b](https://ollama.com/library/qwen3:0.6b) as a small test
model. It is a connectivity/GPU check, not a recommendation for production
agent quality. The pull needs internet access; inference uses the local
weights after the download.

```bash
ollama pull qwen3:0.6b
ollama list
curl --fail --silent --show-error http://127.0.0.1:11434/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3:0.6b","messages":[{"role":"user","content":"Say hello in five words."}],"think":false,"stream":false,"keep_alive":"5m"}'
ollama ps
```

Expect an answer and GPU placement in `ollama ps`. CPU-only execution
does not satisfy the GPU check. Investigate runtime logs and memory
pressure before selecting larger weights or context. Record the model ID,
runtime version and observed placement. The processor column is explained
in [Ollama's GPU check](https://docs.ollama.com/faq#how-can-i-tell-if-my-model-was-loaded-onto-the-gpu).

## 4. Check the office connection and lifecycle

Continue with the [SSH-forwarded inference test](11-arm-inference.md#3-prove-inference-from-the-office-over-ssh).
Keep port 11434 on loopback; neither a public DNS entry nor a public
reverse-proxy route is needed for that test.

Repeat the checks after app restart and after reboot/login. Record whether
operator login/unlock is required and restore the environment before app
launch. Do not label this interactive setup an unattended server until
its startup and recovery have been implemented and tested. Keep the
installed runtime/model inventory and configuration with the host record.

**Done for preparation:** local and forwarded answers work, GPU placement
is confirmed, cloud is disabled, and startup limitations are recorded.
Next is the [node-service implementation and registration gate](11-arm-inference.md#4-complete-the-node-service-before-production-registration).

