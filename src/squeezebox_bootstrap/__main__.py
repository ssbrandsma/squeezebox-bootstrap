from __future__ import annotations

import asyncio

from .server import build_arg_parser, run_server


def main() -> None:
    args = build_arg_parser().parse_args()
    asyncio.run(run_server(args.config, args.debug_protocol, args.log_level))


if __name__ == "__main__":
    main()
