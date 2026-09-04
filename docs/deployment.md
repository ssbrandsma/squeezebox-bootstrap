# Deployment

Target deployment is a small Linux VPS such as AlmaLinux 8/9. Docker Compose is the recommended production path.

## Docker Compose

```bash
cp config.example.json config.json
# Edit config.json and keep the generated UUID unchanged for the life of this server.
uuidgen
docker compose build
docker compose up -d
```

The image uses `python:3.13-slim-bookworm`, installs only this standard-library project, and starts directly as:

```text
python -m squeezebox_bootstrap --config /config/config.json
```

`config.json` is excluded from the image build and mounted read-only at `/config/config.json`. It must contain a valid UUID; startup fails for a missing or malformed value. Use a UUID generated outside the container, place it in `server.uuid`, and retain it across upgrades so device discovery sees the same server identity.

The Compose service runs as UID/GID `10001`, with a read-only root filesystem, all Linux capabilities dropped, and `no-new-privileges`. The application has no runtime persistent state and needs no writable directory or `tmpfs`; Python bytecode creation is disabled. Logs are written to the container standard error stream and are available through Docker.

Useful operations:

```bash
docker compose logs -f
docker compose ps
docker compose restart
docker compose stop
docker compose pull  # only when using a published image instead of the local build
docker compose up -d --build
```

For an upgrade, back up `config.json`, rebuild or pull the selected immutable image, then run `docker compose up -d`. Do not change `server.uuid` unless intentionally creating a new server identity.

## Required Ports

- UDP 3483
- TCP 3483
- TCP 9000

## Notes

- Publish only the listed ports and allow them through the VPS firewall or security group. UDP 3483 is discovery; TCP 3483 is SlimProto; TCP 9000 is Comet/Bayeux.
- Do not use host networking. `compose.yaml` publishes only the required TCP/UDP ports.
- Keep Docker and the host patched. Restrict source IPs at the firewall where possible, especially for a private deployment.
- The image intentionally has no HTTP health endpoint because public catalog mode accepts only the protocol endpoint. Use `docker compose ps`, `docker compose logs`, and an external port/protocol monitor instead.
- Serve applet ZIPs from a separate static server such as `nginx`.
- Keep numeric-IP applet URLs unchanged if older clients depend on them.
