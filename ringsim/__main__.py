"""`python -m ringsim SCENARIO [--port 8100] [--webhook URL] [--speed 60] [--start]`

The token an app must send and the key webhooks are signed with come from the
environment (or `.env` in the working directory): `RINGSIM_TOKEN` (default
`sim-token`), and `RINGSIM_SECRET`, else `RING_WEBHOOK_SECRET`, else
`HMAC_SIGNATURE_KEY` -- the names an app already uses for Ring's.
"""

import argparse
import logging
import os
from pathlib import Path

import uvicorn

from .scenario import load
from .server import Sim, create_app


def _load_env_file(path: Path) -> None:
    """KEY=value lines, never over a variable already set."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> None:
    parser = argparse.ArgumentParser(prog="ringsim", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenario", help="a scenario.json")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--webhook", default="http://127.0.0.1:8000/ring/webhook",
                        help="where to send webhooks; '' sends none")
    parser.add_argument("--speed", type=float, default=60.0,
                        help="simulated seconds per real second")
    parser.add_argument("--tz", help="the scenario's time zone, over its own `tz`")
    parser.add_argument("--start", action="store_true",
                        help="start the day at once, rather than from the page")
    args = parser.parse_args()

    _load_env_file(Path.cwd() / ".env")
    env = os.environ.get
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    sim = Sim(load(args.scenario, args.tz),
              token=env("RINGSIM_TOKEN", "sim-token"),
              secret=env("RINGSIM_SECRET") or env("RING_WEBHOOK_SECRET")
              or env("HMAC_SIGNATURE_KEY") or "change-me",
              webhook_url=args.webhook or None, speed=args.speed)
    if args.start:
        sim.start()
    print(f"Ring simulator: {sim.scenario.title}, {len(sim.scenario.events)} events, "
          f"http://{args.host}:{args.port}")
    uvicorn.run(create_app(sim), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
