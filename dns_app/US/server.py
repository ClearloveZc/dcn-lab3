"""Resolve FS through the course AS, then forward a Fibonacci HTTP request."""

import ipaddress
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from flask import Flask, Response, request

app = Flask(__name__)


def plain(text, status=200):
    return Response(str(text).rstrip("\n") + "\n", status=status, mimetype="text/plain")


@app.get("/healthz")
def health():
    return plain("ok")


@app.get("/fibonacci")
def fibonacci():
    required = ("hostname", "fs_port", "number", "as_ip", "as_port")
    if any(not request.args.get(field) for field in required):
        return plain("hostname, fs_port, number, as_ip and as_port are required", 400)
    hostname = request.args["hostname"]
    try:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", hostname):
            raise ValueError("invalid hostname")
        ports = [request.args[name] for name in ("fs_port", "as_port")]
        if not all(re.fullmatch(r"[0-9]+", value) for value in ports):
            raise ValueError("invalid port")
        fs_port, as_port = map(int, ports)
        if not all(1 <= value <= 65535 for value in (fs_port, as_port)):
            raise ValueError("invalid port")
    except ValueError:
        return plain("invalid hostname or port", 400)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
            udp.settimeout(float(os.environ.get("AS_TIMEOUT", "3")))
            udp.connect((request.args["as_ip"], as_port))
            udp.send(f"TYPE=A\nNAME={hostname}\n".encode("ascii"))
            reply = udp.recv(4096).decode("ascii")
        fields = {}
        for token in reply.split():
            key, value = token.split("=", 1)
            if key in fields:
                raise ValueError("duplicate response field")
            fields[key] = value
        if set(fields) != {"TYPE", "NAME", "VALUE", "TTL"} or fields["TYPE"] != "A" or fields["NAME"].lower() != hostname.lower():
            raise ValueError("invalid AS response")
        if int(fields["TTL"]) < 0:
            raise ValueError("invalid TTL")
        address = str(ipaddress.IPv4Address(fields["VALUE"]))
    except socket.timeout:
        return plain("authoritative server timed out", 504)
    except (OSError, ValueError, UnicodeError):
        return plain("authoritative lookup failed", 502)
    target = f"http://{address}:{fs_port}/fibonacci?" + urllib.parse.urlencode({"number": request.args["number"]})
    try:
        # Use the resolved IP directly; environment proxy settings must not bypass AS.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(target, timeout=float(os.environ.get("FS_TIMEOUT", "5"))) as reply:
            return plain(reply.read().decode("utf-8"), reply.status)
    except urllib.error.HTTPError as exc:
        return plain(exc.read().decode("utf-8"), exc.code)
    except (TimeoutError, socket.timeout):
        return plain("Fibonacci server timed out", 504)
    except (urllib.error.URLError, OSError, UnicodeError):
        return plain("Fibonacci server is unavailable", 502)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
