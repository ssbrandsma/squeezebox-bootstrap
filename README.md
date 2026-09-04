# SqueezeboxBootstrap

SqueezeboxBootstrap is a small, LMS-compatible bootstrap server for legacy Squeezebox/Jive devices. It provides only the discovery, SlimProto, and Comet/Jive behavior required for **Applet Installer** to retrieve applets from a configured catalog.

It is not a music server, library scanner, streaming server, or MySqueezebox replacement.

## What It Supports

- UDP `3483` discovery replies
- TCP `3483` SlimProto sessions for `HELO`, `STAT`, and `META`
- TCP `9000` HTTP `/cometd` with a small Bayeux subset
- Jive `serverstatus`, `status`, `date`, and `jiveapplets` requests in normal mode
- Catalog-only public mode, which permits only `jiveapplets` after the required connection setup

It has been validated with a Logitech Squeezebox Radio for discovery, initial connection, and reconnect behavior. Applet-specific compatibility depends on the selected device firmware, catalog entry, and external ZIP host.

## Architecture

```text
Squeezebox / Jive client
    |
    +-- UDP 3483 --> Discovery response (NAME / JSON / VERS / UUID)
    |
    +-- TCP 3483 --> Minimal SlimProto (HELO / STAT / META, keepalive)
    |
    +-- TCP 9000 --> /cometd
                         |
                         +--> /slim/subscribe
                         +--> /slim/request --> jiveapplets
                                                       |
                                                       v
                                             external applet ZIP URL
```

## Requirements

Choose one runtime:

- Native: Python `3.11` or newer. The project has no third-party runtime dependencies.
- Container: Docker Engine with Docker Compose v2. Docker Desktop is suitable for Windows development; a Linux VPS is recommended for public deployment.

The player must be able to reach these server ports:

- UDP `3483`: discovery
- TCP `3483`: SlimProto player connection
- TCP `9000`: Comet/Bayeux applet catalog requests

## Quick Start

### Docker Compose

Docker is the recommended production deployment. Create the local configuration, generate a stable UUID, edit the catalog, then build and start the service:

```bash
cp config.example.json config.json
uuidgen
# Put the generated UUID in server.uuid, then edit the applet entries.
docker compose build
docker compose up -d
docker compose logs -f
```

Windows PowerShell:

```powershell
Copy-Item config.example.json config.json
[guid]::NewGuid().ToString()
# Put the generated UUID in server.uuid, then edit the applet entries.
docker compose build
docker compose up -d
docker compose logs -f
```

`config.json` is intentionally ignored by Git and excluded from the container image. It is mounted read-only into the running container. Keep a backup of this file, especially its UUID.

### Native Python

Linux/macOS:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
cp config.example.json config.json
python -m squeezebox_bootstrap --config config.json
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
Copy-Item config.example.json config.json
python -m squeezebox_bootstrap --config config.json
```

After installation, the equivalent console command is:

```text
squeezebox-bootstrap --config config.json
```

## Configuration

Start with [config.example.json](config.example.json). The server refuses to start if required values, applet URLs, SHA-1 values, or the server UUID are invalid.

### Server Settings

```json
{
  "server": {
    "name": "Squeezebox Bootstrap",
    "uuid": "11111111-2222-4333-8444-555555555555",
    "host": "0.0.0.0",
    "advertise_ip": "192.0.2.10",
    "http_port": 9000,
    "slimproto_port": 3483,
    "discovery_port": 3483,
    "version": "7.999.999",
    "debug_protocol": false,
    "public_catalog_mode": false
  },
  "applets": []
}
```

- `name`: display name returned to devices. It is informational and is not a hostname the player must resolve.
- `uuid`: a valid UUID identifying this server. Generate it once and retain it across restarts and upgrades.
- `host`: listener address. Use `0.0.0.0` to listen on all IPv4 interfaces.
- `advertise_ip`: IPv4 address returned by discovery. Set it to the reachable LAN address on a multi-homed machine, or the reachable public IPv4 address for an Internet service. Leave it empty only when the server can correctly derive a routed address for each client.
- `http_port`, `slimproto_port`, `discovery_port`: normally remain `9000`, `3483`, and `3483`.
- `version`: compatibility version reported to the player.
- `debug_protocol`: enables bounded protocol payload diagnostics. Keep it `false` outside short troubleshooting sessions.
- `public_catalog_mode`: enables the restricted anonymous catalog mode described below.

The remaining numeric values in `config.example.json` bound TCP connections, Comet streams/sessions, player records, subscriptions, pending events, and per-IP request rates. They have conservative defaults; lower them for a small public catalog and only raise them after observing legitimate traffic.

### Applet Entries

Each item in `applets` is returned by the Jive `jiveapplets` request:

```json
{
  "name": "StandaloneRadio",
  "title": "Standalone Radio",
  "version": "0.3.0",
  "target": "baby",
  "url": "https://downloads.example.net/StandaloneRadio-0.3.0.zip",
  "sha": "0123456789abcdef0123456789abcdef01234567",
  "desc": "Standalone internet radio",
  "creator": "Example",
  "email": ""
}
```

`url` must use `http` or `https`; `sha` must be a 40-character SHA-1 hex value for legacy Jive compatibility. The ZIP file is **not** served by this application. Host it separately on a static HTTPS server and update the URL, version, and SHA-1 together for each release.

Older SqueezeOS/Jive versions may have unreliable DNS behavior when downloading ZIPs. If a numeric-IP URL is known to work for a target device, preserve it exactly.

## Connecting A Player

1. Start the server and confirm it logs all three listeners.
2. Ensure the player can route to the configured `advertise_ip` and the three required ports.
3. For LAN use, connect the player to the same network or configure its external-library/server setting with the server IPv4 address.
4. For Internet use, configure the public IPv4 address, port forwarding/firewall rules, and public mode before sharing the service.
5. In the device's Applet Installer, refresh or select the external library. Available catalog entries should appear and their ZIP URLs are then downloaded directly by the device.

Interface names vary between SqueezeOS/Jive firmware releases. A reboot should not be required for normal reconnects; inspect the logs if discovery or reconnect attempts continue.

## Public Catalog Mode

Set `server.public_catalog_mode` to `true` before exposing the service to untrusted networks. In this mode:

- HTTP accepts only JSON `POST /cometd` requests.
- Only the `jiveapplets` catalog command is dispatched after Bayeux setup.
- Unknown SlimProto commands are rejected.
- The server remains intentionally unauthenticated because legacy player flows do not support application authentication here.

This is a defense-in-depth mode, not an Internet perimeter. See [Security](#security) and [deployment notes](docs/deployment.md) before making the service public.

## Operations

Docker Compose commands:

```bash
docker compose ps
docker compose logs -f
docker compose restart
docker compose stop
docker compose up -d --build
docker compose down
```

To upgrade a local build, back up `config.json`, pull the updated source, then run `docker compose up -d --build`. Keep `server.uuid` unchanged. The container stores no persistent application state.

The container runs as UID/GID `10001` with a read-only root filesystem, all Linux capabilities dropped, and `no-new-privileges`. It requires no writable directory or `tmpfs`; logs go to the container standard error stream.

`http://SERVER:9000/` is not a user interface and should return `404`. The only HTTP protocol endpoint is `/cometd`.

## Diagnostics And Troubleshooting

Run short-lived protocol tracing when diagnosing a device:

```bash
python -m squeezebox_bootstrap --config config.json --debug-protocol
```

Or enable normal debug logging without payload traces:

```bash
python -m squeezebox_bootstrap --config config.json --log-level DEBUG
```

Protocol tracing includes capped hexadecimal payload previews. Turn it off after diagnosis because device identifiers and request content can appear in logs.

Common checks:

- Repeated discovery messages: verify `advertise_ip` is the address the player can reach, not a VPN, loopback, or stale address.
- Player cannot connect: allow TCP `3483` and TCP `9000` through Windows Firewall, the Linux firewall, router port forwarding, and any VPS security group.
- Applet is listed but will not install: verify the device itself can download the configured ZIP URL and that the URL, SHA-1, target, and version match the release.
- Docker will not start: check `docker compose logs`, then verify `config.json` exists beside `compose.yaml` and contains a valid UUID.

## Security

The server enforces bounded UDP datagrams, SlimProto frames, HTTP headers/bodies, read/idle timeouts, connection/session/player limits, and per-IP request limits. It does not accept arbitrary paths, arbitrary filesystem access, dynamic imports, subprocess commands, or ZIP uploads.

### VPS Docker Rate Limits

For the AlmaLinux Docker deployment, [`deploy/squeezebox-docker-firewall`](deploy/squeezebox-docker-firewall) installs host-level limits without affecting other hosted sites. The accompanying [`deploy/squeezebox-docker-firewall.service`](deploy/squeezebox-docker-firewall.service) applies the rules after Docker starts and persists them across reboots.

The rules apply only to the Bootstrap service ports: UDP `3483` is limited to 30 packets per second per source IP (burst 60); TCP `3483` and `9000` are limited to 60 packets per second (burst 120), 20 new connections per minute (burst 30), and 16 concurrent connections per source IP. Established connections are allowed before the limits are evaluated. IPv4 rules use Docker's `DOCKER-USER` chain; IPv6 rules use a dedicated `INPUT` chain for Docker's IPv6 listener. Ports `80` and `443` are not matched or changed.

Install or update the layer as root:

```bash
install -m 0755 deploy/squeezebox-docker-firewall /usr/local/sbin/squeezebox-docker-firewall
install -m 0644 deploy/squeezebox-docker-firewall.service /etc/systemd/system/squeezebox-docker-firewall.service
systemctl daemon-reload
systemctl enable --now squeezebox-docker-firewall.service
```

For public deployment:

- Run on a dedicated, patched Linux VPS rather than a home network.
- Set `public_catalog_mode` to `true`.
- Expose only UDP `3483`, TCP `3483`, and TCP `9000`.
- Enforce host and provider-side TCP/UDP rate limits and use provider DDoS protection, especially for public UDP `3483`.
- Use HTTPS for applet ZIP hosting and restrict release publishing access.
- Monitor container logs, connection-limit warnings, UDP volume, and outbound UDP responses.

See [docs/security.md](docs/security.md) and [docs/deployment.md](docs/deployment.md) for more detail. Container isolation limits the impact of a server compromise, but it cannot prevent link-saturating or distributed denial-of-service attacks.

## Development

Run the test suite:

```bash
python -m unittest discover -s tests -v
python -m compileall -q src
```

## Reference Projects

- [Lyrion Music Server](https://github.com/LMS-Community/slimserver)
- [SqueezePlay](https://github.com/ralph-irving/squeezeplay)
- [Sordino](https://github.com/endegelaende/sordino)
- [SBStandalone](https://github.com/ssbrandsma/SBStandalone)

These projects were used as protocol references only.
