"""python -m web: run the server on this computer, then open http://127.0.0.1:8000"""

import argparse

import uvicorn


def main():
    parser = argparse.ArgumentParser(description="Run Insight by Milton's web server on this computer.")
    parser.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to let other devices on your network in")
    parser.add_argument("--port", type=int, default=8000)
    options = parser.parse_args()
    print(f"Insight by Milton (web) is starting at http://{options.host}:{options.port} (Ctrl+C stops it)")
    uvicorn.run("web.app:app", host=options.host, port=options.port, log_level="info")


if __name__ == "__main__":
    main()
