# Local R5 browser voice gate

`frontend/e2e/r5-voice.spec.ts` uses two isolated Chromium contexts, the existing
fake microphone launch helper, real HTTP/WebSocket signaling and native
RTCPeerConnection. It checks live send/receive tracks, remote audio playback,
increasing audio RTP byte counters in both directions, both participants'
mute/unmute, guest reload with the same identity and fresh host peer, guest leave,
and host end with all retained tracks stopped. A constructor subclass installed
with `addInitScript` retains peers without replacing their behavior. Captured
microphone and receiver tracks remain inspectable after peer closure.

## Requirements and execution (environment owner)

- Existing installed frontend dependencies and Playwright Chromium, or
  `MOSAIQUE_CHROMIUM_PATH` pointing to an installed compatible Chromium.
- Running migrated application database, backend and frontend; seeded
  `MOSAIQUE_HOST_TOKEN`. These tests create meetings in that database.
- Backend configured with `MOSAIQUE_ASR_RUNTIME=fake` and
  `MOSAIQUE_LLM_PROVIDER=fake`. No model service is needed.
- Frontend normally at `http://localhost:5173`, proxying backend HTTP and WS.
  Override `MOSAIQUE_BASE_URL` when needed; microphone access needs localhost or
  HTTPS. Use a single worker for this local gate.

From `frontend`, using existing dependencies only:

```sh
./node_modules/.bin/playwright test e2e/r5-voice.spec.ts --workers=1
```

For the relay gate, generate a fresh local secret (for example with
`openssl rand -hex 32`) and export it as `MOSAIQUE_WEBRTC_TURN_SHARED_SECRET`
in both the backend and Compose shells. No secret is checked in. Start only this
service from the repository root:

```sh
docker compose -f deploy/turn/compose.yaml up -d
```

Configure and restart the backend with:

```sh
export MOSAIQUE_WEBRTC_STUN_URLS='[]'
export MOSAIQUE_WEBRTC_TURN_URLS='["turn:127.0.0.1:3478?transport=udp"]'
# MOSAIQUE_WEBRTC_TURN_SHARED_SECRET must match the Compose environment.
```

Then, from `frontend`:

```sh
MOSAIQUE_R5_RELAY_ONLY=1 ./node_modules/.bin/playwright test e2e/r5-voice.spec.ts --workers=1
```

This variant forces `iceTransportPolicy: relay` in the native constructor and
requires both candidates of the **selected, succeeded pair** to be `relay`,
before and after reload. A gathered relay candidate alone cannot pass. Missing
TURN credentials/connectivity fail the test; the gate never skips or falls back
to direct ICE. To separately exercise the TCP listener, repeat with the backend
TURN URL ending in `?transport=tcp` (relay media remains UDP).

Stop the isolated service after the run:

```sh
docker compose -f deploy/turn/compose.yaml down
```

## Docker Desktop on Mac: relay address mapping

The listener and the advertised relay address serve different purposes.
Host Chromium reaches the TURN listener through `127.0.0.1:3478`. Docker Desktop
does not expose container IPs directly to the host; it forwards published ports.
See [Docker Desktop networking](https://docs.docker.com/desktop/features/networking/).

For this **two clients, same TURN server, forced relay** test, the default relay
address is the fixed container IP `172.30.55.2`. Both clients send through their
TURN allocations; coturn can reach the other allocation on its own private
address. This avoids relying on Mac-to-VM loopback hairpin forwarding. This is
an intentional local test topology, not a configuration for direct-to-relay
peers or remote callers. If the subnet conflicts with a local VPN/network,
change the subnet, static address, relay IP and mapping together.

For a host-reachable relay topology, coturn supports
`external-ip=EXTERNAL/PRIVATE`; relay ports must map to identical external port
numbers. This Compose file publishes only twenty UDP relay ports, 49160–49179,
with identity mapping, and binds every publication to host loopback. See
[coturn external mapping](https://github.com/coturn/coturn/wiki/turnserver) and
[Docker port publication](https://docs.docker.com/engine/network/port-publishing/).
Use a current Docker Engine (28+); older engines have documented localhost
publication isolation caveats.

Do **not** blindly set `MOSAIQUE_TURN_EXTERNAL_IP=127.0.0.1` on Mac: a relayed
peer check aimed at that address can resolve inside the container's loopback,
not the Mac publication. Similarly, `host.docker.internal` locates the host
from a container but is not a substitute for a numeric ICE relay address, and
its gateway IP does not make a loopback-only publication reachable automatically.
The override is provided for deliberately configured environments with a verified
return route, not as a required Mac setup step.

If the default topology fails on the installed Docker Desktop, retain candidate
stats and coturn logs and investigate that environment; do not widen publication
to `0.0.0.0`. An alternative is an already-installed native coturn bound to
`127.0.0.1` for both listening and relay, using these auth/port settings and
`allow-loopback-peers` with `no-cli` for this local-only test. Docker Desktop
host networking is opt-in on 4.34+ and operates at layer 4; it is not equivalent
to Linux interface access and is not assumed here. See
[host networking limitations](https://docs.docker.com/engine/network/drivers/host/).

Validated on 2026-09-14 with Docker Desktop on Mac and Chromium 153: both relay-only
scenarios passed, including selected relay pairs before and after reload, RTP
growth, and leave/end track cleanup. The image's turnserver executable has a
NET_BIND_SERVICE file capability, so Compose retains that single capability
after dropping the others. This gate does not establish cross-network, TURN/TLS,
UDP-blocked, acoustic quality, or real-ASR performance claims. The config disables
TLS and permits private relay peers intentionally; never deploy it publicly.
