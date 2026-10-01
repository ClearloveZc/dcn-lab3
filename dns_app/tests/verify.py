"""Exercise the real HTTP/UDP services, without third-party test dependencies.

Run from a client that can reach US_URL, FS_URL and AS_HOST:AS_PORT.
REGISTER_IP must be an FS IPv4 address reachable from US; REGISTER_AS is
the AS address reachable from both US and FS. See README for Docker usage.
"""

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

US = os.environ.get("US_URL", "http://127.0.0.1:8080")
FS = os.environ.get("FS_URL", "http://127.0.0.1:9090")
AS_HOST = os.environ.get("AS_HOST", "127.0.0.1")
AS_PORT = int(os.environ.get("AS_PORT", "53533"))
REGISTER_IP = os.environ["REGISTER_IP"]
REGISTER_AS = os.environ.get("REGISTER_AS", "as")
REGISTER_AS_PORT = os.environ.get("REGISTER_AS_PORT", "53533")
FS_PORT = os.environ.get("FS_PORT", "9090")
checks = []
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http(base, path, expected_status, expected_body=None, data=None):
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(base + path, method="PUT" if data is not None else "GET",
                                 data=json.dumps(data).encode() if data is not None else None,
                                 headers=headers)
    try:
        response = opener.open(req, timeout=12)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        status, body = response.status, response.read().decode().strip()
    assert status == expected_status, (path, status, body, expected_status)
    if expected_body is not None:
        assert body == expected_body, (path, body, expected_body)
    checks.append({"kind": "HTTP", "request": req.full_url, "method": req.method,
                   "status": status, "body": body, "passed": True})


def udp(message, expected):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(5)
        sock.connect((AS_HOST, AS_PORT))
        sock.send(message.encode())
        reply = sock.recv(4096).decode()
    assert reply == expected, (message, reply, expected)
    checks.append({"kind": "UDP", "request": message, "response": reply, "passed": True})


def query(**changes):
    params = {"hostname": "fibonacci.com", "fs_port": FS_PORT, "number": "10",
              "as_ip": REGISTER_AS, "as_port": REGISTER_AS_PORT}
    params.update(changes)
    return "/fibonacci?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})


if __name__ == "__main__":
    http(FS, "/healthz", 200, "ok")
    http(US, "/healthz", 200, "ok")
    for n, answer in [(0, "0"), (1, "1"), (2, "1"), (10, "55"), (100, "354224848179261915075")]:
        http(FS, f"/fibonacci?number={n}", 200, answer)
    for value in ("hello", "1.5", "-1", ""):
        http(FS, "/fibonacci?number=" + value, 400)
    http(FS, "/fibonacci", 400)
    payload = {"hostname": "fibonacci.com", "ip": REGISTER_IP,
               "as_ip": REGISTER_AS, "as_port": REGISTER_AS_PORT}
    for missing in payload:
        http(FS, "/register", 400, data={k: v for k, v in payload.items() if k != missing})
    http(FS, "/register", 400, data={**payload, "ip": "not-an-ip"})
    http(FS, "/register", 400, data={**payload, "as_port": "1.5"})
    http(FS, "/register", 201, "registered", data=payload)
    udp("TYPE=A\nNAME=fibonacci.com\n",
        f"TYPE=A\nNAME=fibonacci.com VALUE={REGISTER_IP} TTL=10\n")
    for missing in ("hostname", "fs_port", "number", "as_ip", "as_port"):
        http(US, query(**{missing: None}), 400)
    http(US, query(), 200, "55")
    http(US, query(number="20"), 200, "6765")
    http(US, query(number="hello"), 400)
    http(US, query(fs_port="65536"), 400)
    http(US, query(hostname="not-registered.invalid"), 502)
    udp("TYPE=A\nNAME=not-registered.invalid\n", "ERROR=NOT_FOUND\n")
    udp("TYPE=AAAA\nNAME=fibonacci.com\n", "ERROR=BAD_REQUEST\n")
    udp("TYPE=A\nNAME=x VALUE=bad TTL=10\n", "ERROR=BAD_REQUEST\n")
    udp("TYPE=A\nNAME=x VALUE=127.0.0.1 TTL=-1\n", "ERROR=BAD_REQUEST\n")
    udp("TYPE=A\nNAME=x NAME=y\n", "ERROR=BAD_REQUEST\n")
    # Use a separate record to test idempotent registration and replacement.
    for address in ("127.0.0.1", "127.0.0.2", "127.0.0.2"):
        udp(f"TYPE=A\nNAME=update-test.example VALUE={address} TTL=10\n", "OK\n")
    udp("TYPE=A\nNAME=update-test.example\n",
        "TYPE=A\nNAME=update-test.example VALUE=127.0.0.2 TTL=10\n")
    print(json.dumps({"checked_at_utc": datetime.now(timezone.utc).isoformat(),
                      "count": len(checks), "checks": checks}, indent=2))
