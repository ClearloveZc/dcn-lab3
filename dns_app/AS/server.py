"""Lab 3 authoritative directory using the handout's text protocol over UDP."""

import ipaddress
import logging
import os
import re
import socket
import sqlite3
from pathlib import Path

LOG = logging.getLogger("authoritative")


def parse_message(data):
    fields = {}
    for token in data.decode("ascii").split():
        key, value = token.split("=", 1)
        if key in fields or not value:
            raise ValueError("duplicate or empty field")
        fields[key] = value
    if fields.get("TYPE") != "A":
        raise ValueError("only TYPE=A is supported")
    name = fields.get("NAME", "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", name):
        raise ValueError("invalid hostname")
    if set(fields) not in ({"TYPE", "NAME"}, {"TYPE", "NAME", "VALUE", "TTL"}):
        raise ValueError("unexpected or missing fields")
    return fields


def respond(db, data):
    try:
        fields = parse_message(data)
        name = fields["NAME"]
        if "VALUE" in fields:
            address = str(ipaddress.IPv4Address(fields["VALUE"]))
            ttl = int(fields["TTL"])
            if ttl < 0 or ttl > 2147483647:
                raise ValueError("invalid TTL")
            with db:
                db.execute(
                    "INSERT INTO records(name, address, ttl) VALUES (?, ?, ?) "
                    "ON CONFLICT(name) DO UPDATE SET address=excluded.address, ttl=excluded.ttl",
                    (name.lower(), address, ttl),
                )
            LOG.info("registered %s -> %s TTL=%s", name, address, ttl)
            return b"OK\n"
        record = db.execute(
            "SELECT address, ttl FROM records WHERE name=?", (name.lower(),)
        ).fetchone()
        if record is None:
            return b"ERROR=NOT_FOUND\n"
        address, ttl = record
        return f"TYPE=A\nNAME={name} VALUE={address} TTL={ttl}\n".encode("ascii")
    except (ValueError, UnicodeError):
        return b"ERROR=BAD_REQUEST\n"


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    path = Path(os.environ.get("DB_PATH", "data/records.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS records "
                   "(name TEXT PRIMARY KEY, address TEXT NOT NULL, ttl INTEGER NOT NULL)")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            server.bind(("0.0.0.0", int(os.environ.get("PORT", "53533"))))
            LOG.info("UDP server listening on %s", server.getsockname())
            while True:
                data, peer = server.recvfrom(4096)
                server.sendto(respond(db, data), peer)


if __name__ == "__main__":
    main()
