# R1 — Azure and Rust ASR deployment configuration

Status: configuration prepared for review; **hardware feasibility blocked**.
R0 merged as [PR #19](https://github.com/Aymenec-212/isaac/pull/19), baseline
`9bb417a`. R1 creates no Azure resources and makes no application changes.

## Files and boundaries

- [Bicep](../infra/azure/main.bicep): two Ubuntu VMs, two subnets/NSGs, two static
  public IPs and separate 128 GiB data disks. OS disks are 64 GiB. App: B2s;
  GPU: NC4as_T4_v3. Explicit deny overrides the default VNet inbound allow.
- [Parameter example](../infra/azure/main.bicepparam.example) and
  [parameter guard](../infra/azure/check-parameters.py): exact OS image version,
  operator public IPv4 /32, public SSH key. No secret values in Bicep outputs.
- [ASR image](../deploy/asr/Dockerfile), [Compose](../deploy/asr/compose.yaml),
  [server config](../deploy/asr/config.toml): private-address port publication,
  non-root read-only container, file-based API key, temporary config/logs, one
  NVIDIA device, batch two, F16 LM. Optional audio/token logging is omitted.
- [Model lock](../deploy/asr/model-lock.json) and
  [downloader](../deploy/asr/download-model.py): immutable model revision and
  SHA256/size verification before atomic installation. No runtime HF downloads.

This provides the GPU deployment candidate and infrastructure definition. App
image/Compose repairs, PostgreSQL/audio mounts in the app stack, TLS proxy and
actual coturn service belong to R5/R6. The app VM is reserved infrastructure;
its web/TURN NSG rules do not imply that those services have been installed.
Neither TCP listening nor a successful config parse proves ASR readiness. R2
must exercise Ready, inference progress, two slots, tail flush and slot release.

## Immutable inputs and remaining build gate

| Input | Pin |
|---|---|
| moshi source | `e6a55d2722a65870ef52a6c9f6ecfc0e90f38362`; Cargo uses upstream `Cargo.lock` with `--locked` |
| STT model | `kyutai/stt-1b-en_fr-candle` revision `095e38f6242006a93c2541149b181988397f5c7c`; all three files hashed in model-lock.json |
| Rust | 1.89.0, official image digest in Dockerfile |
| CUDA | 12.8.1 Ubuntu 24.04 devel/runtime image digests in Dockerfile; T4 compute capability 75 |
| Ubuntu VM | Canonical `ubuntu-24_04-lts:server:24.04.202607280`, returned in West Europe on 2026-09-12; recheck availability before provisioning |
| Deployment validators used | Bicep 0.44.1; Docker Compose 5.0.2; Python 3.12+ for helpers |

The source, weights and base images are pinned; the **built image does not yet
have a digest**. Apt resolves build/runtime OS packages at build time, so this
is not a byte-for-byte hermetic build. Record the installed package inventory
and publish the resulting image by digest before deployment. Build on an amd64
Linux builder; do not pretend an unbuilt Dockerfile proves CUDA compatibility.
The local Docker Desktop daemon was manually paused, and no image build ran.
No GPU weights were downloaded in R1 (metadata/checksums only).

Host NVIDIA driver and NVIDIA Container Toolkit versions must be selected,
pinned and recorded with the first approved host preparation. Use the official
[CUDA compatibility guidance](https://docs.nvidia.com/deploy/cuda-compatibility/)
and [Container Toolkit installation guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
A suitable driver, `nvidia-smi`, container device injection and dynamic-library
resolution remain hardware gates, not facts established by this PR.

## Subscription and cost evidence — 2026-09-12

Read-only CLI observations, identifiers omitted:

| Check | Result |
|---|---|
| `az account show --query '{name:name,state:state}'` | Microsoft Azure Sponsorship / Enabled |
| West Europe `az vm list-usage`, T4/total cores filter | `[]`; capacity is not established |
| `az vm list-skus --location westeurope --size Standard_NC4as_T4_v3 --all` | **Location restriction: NotAvailableForSubscription**, West Europe |
| B2s SKU restrictions | Zones 2/3 restricted; template requests no zone. Actual regional allocation remains unverified. |
| Ubuntu image list | Exact version recorded above |
| Credit balance / expiry | Not verified through CLI; maintainer must confirm in the subscription's credit portal |

The T4 restriction blocks provisioning and R2 hardware validation. Resolve it
with the intended subscription/support, or review an explicit regional/SKU
amendment. Do not remove the template's West Europe restriction or enable billing
as an incidental workaround. No resource group, VM, disk or budget was created.

Public Linux consumption prices were refreshed from the
[Azure retail API](https://prices.azure.com/api/retail/prices) for West Europe.
Filters: `priceType eq 'Consumption'`; VM ARM SKUs B2s/NC4as_T4_v3, excluding
Windows/Spot/Low Priority; disk meters E6/E10 LRS Disk; Standard IPv4 Static Public IP.

| Resource | Rate | Estimate: 720 app hours / 40 GPU hours, disks and IPs retained |
|---|---:|---:|
| B2s | $0.048/hour | $34.56 |
| NC4as_T4_v3 | $0.658/hour | $26.32 |
| Two 64 GiB OS disks (E6 LRS) | $4.80/disk-month | $9.60 |
| Two 128 GiB data disks (E10 LRS) | $9.60/disk-month | $19.20 |
| Two Standard static IPv4 addresses | $0.005/address-hour | $7.20 |
| **Baseline estimate** | | **$96.88** |

Continuous GPU allocation for 720 hours makes the same baseline **$544.32**.
Monthly disk meters are estimated for one billing month rather than asserting
that every month has 720 hours. Disk operations ($0.002/10k for E6/E10), network
traffic, registry/build services, DNS, backup, tax and external LLM charges are
additional. Shared-disk mount meters do not apply: these disks are not configured
as shared disks. Credit coverage and actual negotiated prices are unverified.

## Runbook: review and feasibility first

Run commands from the repository root unless a directory change is shown.
Python helpers need Python 3.12+ (the existing backend venv is sufficient).

1. Review this PR. Confirm subscription ID, remaining credit/expiry and the
   intended deployment ceiling privately; keep subscription IDs and keys out of
   reports. Resolve the T4 restriction and check both VM SKU restrictions, total
   regional cores and GPU-family quota again. Empty usage results fail the gate.
2. Recheck exact OS image availability. Copy the parameter example to
   `infra/azure/validation.local.bicepparam`, replace all placeholders (use the
   exact version above if still available), and validate locally:

   ```sh
   az bicep build --file infra/azure/main.bicep --outfile /tmp/mosaique-arm.json
   az bicep build-params --file infra/azure/validation.local.bicepparam --outfile /tmp/mosaique-params.json
   python3 infra/azure/check-parameters.py /tmp/mosaique-params.json
   docker compose --env-file deploy/asr/.env.example -f deploy/asr/compose.yaml config --quiet
   python3 -m unittest discover -s deploy/asr -p 'test_*.py' -v
   ```

3. Before allocating resources, obtain review of the completed parameters,
   budget and feasibility evidence. After that review, create a dedicated
   resource group (if absent), run `az deployment group validate` and
   `az deployment group what-if` using the compiled template/parameters, inspect
   the changes, then use `az deployment group create`. These Azure-side checks
   have **not** run in R1. Budget alerts are not spending caps.
4. Restrict SSH to the operator /32 on the app; reach the GPU at `10.20.2.4`
   through the app using ProxyJump. The GPU public IP exists only for explicit
   outbound downloads; its NSG admits port 22/8080 only from `10.20.1.4`.
   Keep Docker ports bound as specified: Docker-published ports can bypass UFW.
5. Prepare the hosts after provisioning: install Docker Engine/Compose; on GPU,
   install and record the selected NVIDIA driver/toolkit versions, reboot as
   required, configure the NVIDIA container runtime, and verify GPU injection.
   Identify **data disk LUN 0** using `lsblk` and `/dev/disk/azure/`. Format only a
   confirmed empty newly created disk; mount by UUID at `/srv/mosaique` and add
   a persistent fstab entry. Never format on rerun or format the OS/temporary disk.
   Verify the mount before creating directories, and require the mount before
   starting Compose so data cannot silently fall onto the OS disk. App DB/audio
   directory integration follows in R6.
6. Download weights on the GPU host to `/srv/mosaique/models` using
   `python3 deploy/asr/download-model.py /srv/mosaique/models`. Verify read access
   for UID 10001. Store a random URL-safe 32–128-character ASR key under
   `/etc/mosaique/asr_api_key`, owner UID 10001, mode 0400, within a protected
   directory. File-backed Compose secrets retain host permissions; do not assume
   Compose's uid/mode settings can fix them. Give the same key to the app through
   protected configuration. Never put it in a command argument or report.
7. Build on an amd64 builder with enough RAM/disk (not the small app VM), then
   publish to the reviewed registry and record its immutable digest and installed
   package inventory. Copy `.env.example` to ignored `deploy/asr/.env`, use the
   build tag for `docker compose build asr`, then set `ASR_IMAGE` to the published
   `repository@sha256:...` for deployment. Start with `docker compose up -d --no-build`
   from `deploy/asr/`. The key is injected into mode-0600 ephemeral TOML;
   no static public credential is accepted. Preserve the last successful digest
   and lock/config checksums with the report.
8. Check container startup, missing shared libraries, `nvidia-smi`, logs and
   filesystem output. From the app host, verify invalid-key rejection and that
   outside-VNet ASR access fails. R2 must then run the real protocol/concurrency
   probe before any meeting admission. Existing remote adapter readiness is
   still unknown; this PR does not repair it.
9. For native local development, retain MLX/fake. For R2, tunnel the private ASR
   port through the app/GPU SSH route and configure `MOSAIQUE_ASR_RUNTIME=moshi_server`
   with the existing URL/key/precision settings. No transport/domain types change.

No automated host bootstrap formats disks or downloads/runs privileged installers
in this slice. Host preparation and image build must be recorded as executed
before the deployment is called reproducible in practice.

## Stop, rollback and next gate

With no active meeting, stop/drain ASR and deallocate the GPU VM through Azure;
verify `PowerState/deallocated`. Stopping only the OS/container does not stop
compute charges. Retained disks and static IPs keep billing. Do not delete the
resource group as a routine stop operation: it also deletes durable data.

Rollback means the last successful image digest and config, not a mutable tag.
There is no DB migration in R1. Data disks/OS disks have detach-on-VM-delete
behavior, which does not protect them against resource-group deletion. Reattach
existing data disks explicitly for a replacement VM; do not redeploy an Empty
disk definition over data without reviewing what-if and backup state.

R1 local validation: Bicep compilation, Compose schema resolution and five
helper failure tests pass. GPU provisioning/build/startup and Azure-side
validate/what-if remain unverified. After review/merge and feasibility resolution,
R2 corrects and validates two real independent ASR streams. Do not start R2 in
this PR or describe the two-user milestone as implemented.

Upstream references: [pinned server](https://github.com/kyutai-labs/moshi/tree/e6a55d2722a65870ef52a6c9f6ecfc0e90f38362/rust/moshi-server),
[pinned weights](https://huggingface.co/kyutai/stt-1b-en_fr-candle/tree/095e38f6242006a93c2541149b181988397f5c7c),
[VM Bicep schema](https://learn.microsoft.com/en-us/azure/templates/microsoft.compute/2024-07-01/virtualmachines),
[GPU Compose](https://docs.docker.com/compose/how-tos/gpu-support/).

## Repository regression checks — 2026-09-12

- `cd backend && UV_CACHE_DIR=/private/tmp/mosaique-uv uv run --no-sync pytest -q -m 'not integration and not slow'`: **305 passed, 94 deselected**.
- Backend `uv run --no-sync ruff check .` and `ruff format --check .`: pass, 147 files formatted.
- Backend `uv run --no-sync mypy`: **8 errors in unchanged `speech/adapters/kyutai/mlx_runtime.py`**, among 99 files checked. Local installed MLX modules lack explicitly exported/type-visible LmConfig, Lm, quantize, mimi_202407, LmGen and Sampler. R1 changes no backend source or dependencies; this is not marked green.
- `cd frontend && npm test -- --cache=false`: **91 passed**, 9 files; `npm run typecheck` and `npm run build`: pass.
- New helpers: `backend/.venv/bin/ruff check deploy/asr/*.py infra/azure/*.py` and matching `ruff format --check`: pass.
- `git diff --check` and local document-link checks: pass.

Database integration, slow/model tests and Playwright calls were not rerun;
Docker Desktop is manually paused. The deployment helper suite is additional
local coverage, not evidence of a running container or Azure deployment.
