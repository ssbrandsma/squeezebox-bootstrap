# Protocol Research

Date: 2026-09-03

This document distinguishes verified source findings from inference. No local packet capture files were present in `research/pcaps/` during this implementation, so PCAP-backed claims remain unverified unless noted otherwise.

## Upstream Sources Studied

- Lyrion Music Server `Slim/Web/Cometd.pm`
- Lyrion Music Server `Slim/Networking/Slimproto.pm`
- Lyrion Music Server `Slim/Player/Squeezebox.pm`
- Lyrion Music Server `Slim/Control/Jive.pm`
- Lyrion Music Server `Slim/Control/Queries.pm`
- SqueezePlay `share/applets/SetupAppletInstaller/SetupAppletInstallerApplet.lua`
- Sordino `share/jive/applets/SetupAppletInstaller/SetupAppletInstallerApplet.lua`
- Sordino `jive/net/comet.py`
- Sordino `jive/applets/SlimDiscovery/SlimDiscoveryApplet.py`

## UDP 3483 Discovery

VERIFIED FROM UPSTREAM SOURCE

- Jive/SqueezePlay discovery requests are TLV-like and start with lowercase `e`.
- Sordino's discovery request builder asks for `IPAD`, `NAME`, `JSON`, `VERS`, `UUID`, and includes a `JVID` field. LMS's discovery handler returns `IPAD` as a string IPv4 address, `JSON` as a string port, and omits informational `JVID` from the reply.
- Discovery responses start with uppercase `E`.
- Fields are encoded as `TAG` + one-byte length + raw value bytes.

STILL UNVERIFIED

- Exact stock Radio packet cadence and whether it always includes the same field set.
- Whether any additional fields are required by firmware `7.7.3 r16676`.

## TCP 3483 SlimProto

VERIFIED FROM UPSTREAM SOURCE

- Client-to-server SlimProto frames are parsed as `4-byte opcode` + `4-byte big-endian payload length` + payload.
- LMS buffers partial TCP reads and can consume multiple frames from one read.
- New TCP sessions are closed if no `HELO` arrives within roughly 5 seconds.
- Server-to-player frames use `2-byte big-endian length including opcode` + `4-byte opcode` + payload.

## HELO

VERIFIED FROM UPSTREAM SOURCE

- LMS accepts two common `HELO` payload layouts: without UUID and with UUID.
- Parsed fields include `deviceid`, `revision`, 6-byte MAC, optional 16-byte UUID-as-hex, bit flags in `wlan_channellist`, cumulative bytes received, and a 2-byte language code.
- Extra trailing bytes are treated as capability text.

INFERRED

- For bootstrap purposes, the essential server behavior is probably: parse and retain identity fields, mark the player connected, and keep the TCP session alive.

## STAT

VERIFIED FROM UPSTREAM SOURCE

- `STAT` payloads are binary and include an event code plus buffer, timing, byte-count, and error fields.
- LMS uses these to update liveness and playback-related state.

INFERRED

- For bootstrap-only behavior, only a tiny subset is needed: recognize the frame, update `last_seen`, and optionally log the event code.

## META

VERIFIED FROM UPSTREAM SOURCE

- LMS routes `META` frames to direct metadata handling and logs the payload length.

INFERRED

- The bootstrap server does not need to interpret `META` deeply for Applet Installer.

## `strm/t`

VERIFIED FROM UPSTREAM SOURCE

- LMS constructs `strm` payloads as 24-byte binary control blocks and sends them with opcode `strm`.
- For the `t` command, LMS sets the command byte to `t`, leaves most fields neutral, and sends zeroes for server IP/port.

INFERRED

- A periodic `strm-t` keepalive is likely useful to preserve an apparently healthy session even when no streaming is active.

NOT YET VERIFIED

- Exact minimum cadence required by a physical Radio.

## HTTP `/cometd`

VERIFIED FROM UPSTREAM SOURCE

- LMS accepts Bayeux messages as a JSON array.
- It supports `application/json` bodies and URL-encoded `message=` forms.
- The Bayeux protocol version is `1.0`.

## Comet / Bayeux

VERIFIED FROM UPSTREAM SOURCE

- Supported meta channels include `/meta/handshake`, `/meta/connect`, `/meta/reconnect`, `/meta/disconnect`, `/meta/subscribe`, and `/meta/unsubscribe`.
- LMS handshake responses include `supportedConnectionTypes` containing `long-polling` and `streaming`.
- Invalid or unknown `clientId` values cause advice requesting a fresh handshake.
- LMS keeps long-poll requests open up to about 60 seconds.

INFERRED

- Implementing `streaming` plus basic `long-polling` fallback is the safest minimal subset for bootstrap work.

## `/slim/request` and `/slim/subscribe`

VERIFIED FROM UPSTREAM SOURCE

- `SetupAppletInstaller` sends a user request containing:
  - command `jiveapplets`
  - `target:<machine>`
  - `version:<major.minor.patch>`
- Sordino's Comet client sends `/slim/request` with:
  - `data.request = [playerid_or_empty, [command, ...args]]`
  - `data.response = "/<clientId>/slim/request"`
- `/slim/subscribe` uses a similar structure, but the response path is the subscribed channel under the client ID.

NOT YET VERIFIED

- Exact stock Radio request envelope on firmware `7.7.3`, including whether the response path also contains a request ID suffix.

## `serverstatus`, `status`, and `date`

VERIFIED FROM UPSTREAM SOURCE

- Jive/Sordino subscribes to `/slim/serverstatus` with request `["serverstatus", 0, 50, "subscribe:60"]`.
- Player status subscriptions use the `status` CLI command rather than the literal `playerstatus` command.
- LMS `serverstatus` responses include `version`, `uuid`, `ip`, `httpport`, `player count`, and `players_loop`.
- LMS `status` responses include `player_name`, `player_connected`, `power`, `mode`, and playback-oriented fields.
- Jive `date` responses include `date_epoch` and a placeholder ISO-like `date` string.

INFERRED

- A bootstrap server can probably satisfy the Radio with a much smaller subset of these fields than LMS emits.

## `jiveapplets` Response Shape

VERIFIED FROM UPSTREAM SOURCE

- LMS returns `count` and `item_loop`.
- `SetupAppletInstaller` expects applet entries containing at least enough metadata to show title/name/version and download a ZIP via `url` or `relurl`.
- Existing LMS plugin-management code also normalizes `creator`, `desc`, `email`, and lowercase SHA-1 values.

INFERRED

- Mandatory practical fields for this project are likely `name`, `title`, `version`, `url`, and `sha`.

## Current Unknowns

NOT YET VERIFIED

- Initial end-to-end Radio connection order across UDP, SlimProto, and Comet on stock firmware `7.7.3 r16676`
- exact minimum `strm-t` keepalive interval
- whether the Radio prefers streaming Comet only or also tolerates long-polling reconnects
- whether additional `serverstatus` or `status` fields are required before Applet Installer appears stable
