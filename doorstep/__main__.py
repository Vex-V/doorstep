"""`python -m doorstep [--host H] [--port P]`: run the server."""

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(prog="doorstep")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run("doorstep.app:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
