"""Fibonacci HTTP server and registration client for the Lab 3 AS."""

import ipaddress
import os
import re
import socket
import sys
from flask import Flask, Response, request

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8192
# Fibonacci results can exceed Python's default decimal conversion limit.
if hasattr(sys, "set_int_max_str_digits"):
    sys.set_int_max_str_digits(0)


def plain(text, status=200):
    return Response(str(text) + "\n", status=status, mimetype="text/plain")


def fib_pair(n):
    """Return (F(n), F(n+1)) in O(log n) doubling steps."""
    if n == 0:
        return 0, 1
    a, b = fib_pair(n // 2)
    c, d = a * (2 * b - a), a * a + b * b
    return (d, c + d) if n % 2 else (c, d)


@app.get("/healthz")
def health():
    return plain("ok")


@app.get("/fibonacci")
def fibonacci():
    value = request.args.get("number", "")
    if not re.fullmatch(r"[+]?[0-9]+", value):
        return plain("number must be a nonnegative integer", 400)
    try:
        number = int(value)
        return plain(fib_pair(number)[0])
    except (ValueError, RecursionError, OverflowError):
        return plain("invalid number", 400)


@app.put("/register")
def register():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return plain("a JSON object is required", 400)
    try:
        hostname = payload["hostname"]
        if not isinstance(hostname, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", hostname):
            raise ValueError("invalid hostname")
        ip = str(ipaddress.IPv4Address(payload["ip"]))
        as_host = payload["as_ip"]
        if not isinstance(as_host, str) or not as_host.strip():
            raise ValueError("invalid as_ip")
        port_value = payload["as_port"]
        if isinstance(port_value, bool) or not re.fullmatch(r"[0-9]+", str(port_value)):
            raise ValueError("invalid port")
        as_port = int(port_value)
        if not 1 <= as_port <= 65535:
            raise ValueError("invalid port")
    except (KeyError, TypeError, ValueError):
        return plain("hostname, ip, as_ip and a valid as_port are required", 400)
    message = f"TYPE=A\nNAME={hostname} VALUE={ip} TTL=10\n".encode("ascii")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
            udp.settimeout(float(os.environ.get("AS_TIMEOUT", "3")))
            udp.connect((as_host, as_port))
            udp.send(message)
            ack = udp.recv(4096)
        if ack.strip() != b"OK":
            return plain("authoritative server rejected registration", 502)
    except socket.timeout:
        return plain("authoritative server timed out", 504)
    except OSError:
        return plain("authoritative server is unavailable", 502)
    return plain("registered", 201)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "9090")))
