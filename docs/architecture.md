# Architecture

SqueezeboxBootstrap is intentionally small. It exposes three protocol surfaces:

- `discovery.py`: UDP 3483 request parsing and TLV response building
- `slimproto.py`: TCP 3483 message framing and minimal player tracking
- `http.py` + `cometd.py` + `jive.py`: HTTP `/cometd`, Bayeux session handling, and the tiny Jive command dispatcher

The server keeps only in-memory state:

- connected players
- Bayeux client sessions
- active subscriptions needed for `serverstatus`, `playerstatus`, and `datestatus`

There is no database, plugin loader, shell execution, file upload path, or generic web UI.

