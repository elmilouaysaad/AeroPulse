"""Week 2 poller: adsb.lol primary, adsb.fi fallback, Kafka producer."""
from __future__ import annotations

import argparse
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import requests
import structlog
from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST

from .parser import parse_response
from .producer import build_producer, produce_vectors

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
)
log = structlog.get_logger()

POLLS_TOTAL = Counter(
    "aeropulse_polls_total", "Polls by source and status", ["source", "status"]
)
AIRCRAFT_GAUGE = Gauge(
    "aeropulse_aircraft_count", "Aircraft seen in the last successful poll"
)
PARSE_ERRORS = Counter(
    "aeropulse_parse_errors_total", "Records that failed parsing"
)

ADSB_LOL = "https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{radius}"
ADSB_FI = "https://opendata.adsb.fi/api/v3/lat/{lat}/lon/{lon}/dist/{radius}"


def fetch(url: str, timeout: int = 10) -> dict:
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def fetch_with_fallback(lat: float, lon: float, dist: int) -> tuple[dict, str]:
    try:
        payload = fetch(ADSB_LOL.format(lat=lat, lon=lon, radius=dist))
        POLLS_TOTAL.labels(source="adsb.lol", status="success").inc()
        return payload, "adsb.lol"
    except (requests.RequestException, ValueError) as exc:
        log.warning("adsb_lol_failed", error=str(exc))
        POLLS_TOTAL.labels(source="adsb.lol", status="failed").inc()
        payload = fetch(ADSB_FI.format(lat=lat, lon=lon, radius=dist))
        POLLS_TOTAL.labels(source="adsb.fi", status="success").inc()
        return payload, "adsb.fi"


def run(lat: float, lon: float, dist: int, interval: int, iterations: int) -> None:
    producer = build_producer()
    for i in range(iterations):
        try:
            payload, source = fetch_with_fallback(lat, lon, dist)
            vectors = parse_response(payload)
            AIRCRAFT_GAUGE.set(len(vectors))
            sent = produce_vectors(producer, vectors)
            log.info(
                "poll_succeeded",
                iteration=i + 1,
                source=source,
                aircraft_count=len(vectors),
                kafka_messages=sent,
            )
        except Exception as exc:
            PARSE_ERRORS.inc()
            log.error("poll_failed", exc_info=exc)
        if i < iterations - 1:
            time.sleep(interval)
    producer.flush(10)


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/metrics":
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE_LATEST)
            self.end_headers()
            self.wfile.write(generate_latest())
        else:
            self.send_response(404)
            self.end_headers()


def start_metrics_server(port: int = 8000) -> None:
    server = HTTPServer(("0.0.0.0", port), MetricsHandler)
    Thread(target=server.serve_forever, daemon=True).start()
    log.info("metrics_server_started", port=port)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--dist", type=int, default=100, help="nautical miles, max 250")
    p.add_argument("--interval", type=int, default=15)
    p.add_argument("--iterations", type=int, default=10)
    p.add_argument("--metrics-port", type=int, default=8000)
    args = p.parse_args()
    start_metrics_server(args.metrics_port)
    run(args.lat, args.lon, args.dist, args.interval, args.iterations)


if __name__ == "__main__":
    main()