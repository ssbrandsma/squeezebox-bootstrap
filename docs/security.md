# Security

This project is designed as a small network-facing service, so the implementation keeps strict limits:

- bounded UDP datagram parsing
- bounded SlimProto frame sizes
- bounded HTTP header and body sizes
- explicit read and idle timeouts
- fixed supported paths and command names
- no dynamic imports from config
- no subprocess calls from network input
- no arbitrary filesystem access from requests
- no ZIP hosting feature

The applet catalog is configuration-driven only. ZIP URLs are validated at startup, but the files themselves are expected to be served by a separate static HTTP server.

