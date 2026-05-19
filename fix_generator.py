#!/usr/bin/env python3
"""
FIX 4.4 Message Generator for B3 EntryPoint (PUMA Trading System).

Generates realistic FIX message flows for testing BindPlane Blueprints,
following the B3 EntryPoint Message Specification v2.40.

Usage:
    python fix_generator.py --flow 1                  # SOH separator (binary)
    python fix_generator.py --flow 1 --readable       # '|' separator (debug)
    python fix_generator.py --flow 5 --output out.fix
    python fix_generator.py --list-flows
"""

from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable

SOH = "\x01"
READABLE_SEP = "|"

SENDER = "BROKER01"
TARGET = "B3ENTRYPOINT"
EXCHANGE = "BVMF"
CAU_USER = "CAUUSER01"
CAU_PASS = "PASS1234"
ACCOUNT = "0000123456"

ASSETS = {
    "PETR4":  {"price": 38.50, "segment": "Equities"},
    "VALE3":  {"price": 62.10, "segment": "Equities"},
    "ITUB4":  {"price": 31.80, "segment": "Equities"},
    "WINQ25": {"price": 135000.0, "segment": "Derivatives"},
    "DOLQ25": {"price": 5890.0, "segment": "Derivatives"},
    "USDBRL": {"price": 5.895, "segment": "FX"},
}


# ---------------------------------------------------------------------------
# Core message assembly
# ---------------------------------------------------------------------------

def fmt_ts(dt: datetime) -> str:
    """FIX UTCTimestamp with millisecond precision."""
    return dt.strftime("%Y%m%d-%H:%M:%S.") + f"{dt.microsecond // 1000:03d}"


def fmt_price(price: float) -> str:
    if price == int(price):
        return f"{price:.1f}"
    return f"{price:.2f}"


def build_message(msg_type: str, sender: str, target: str, seq: int,
                  sending_time: datetime, body_fields: list[tuple[int, str]]) -> str:
    """
    Assemble a FIX 4.4 message with correct BodyLength (9) and Checksum (10).

    Uses SOH internally; caller can swap separators afterwards.

    BodyLength = bytes after `9=<len><SOH>` up to and INCLUDING the SOH
                 immediately before `10=`.
    Checksum   = sum of every byte from `8=...` up to and including the
                 SOH before `10=`, modulo 256, formatted as 3 digits.
    """
    header_tail = [
        (49, sender),
        (56, target),
        (34, str(seq)),
        (52, fmt_ts(sending_time)),
    ]

    body_parts = [f"35={msg_type}"]
    body_parts += [f"{tag}={val}" for tag, val in header_tail]
    body_parts += [f"{tag}={val}" for tag, val in body_fields]
    body = SOH.join(body_parts) + SOH
    body_length = len(body.encode("ascii"))

    prefix = f"8=FIX.4.4{SOH}9={body_length}{SOH}"
    pre_checksum = prefix + body
    checksum = sum(pre_checksum.encode("ascii")) % 256
    return pre_checksum + f"10={checksum:03d}{SOH}"


# ---------------------------------------------------------------------------
# Session state — tracks sequence numbers per direction
# ---------------------------------------------------------------------------

@dataclass
class Session:
    client_seq: int = 1
    server_seq: int = 1
    clock: datetime = field(default_factory=lambda: datetime(2026, 5, 19, 13, 0, 0, tzinfo=timezone.utc))
    messages: list[tuple[str, str]] = field(default_factory=list)  # (direction, raw)

    def tick(self, ms: int = 50) -> datetime:
        self.clock += timedelta(milliseconds=ms)
        return self.clock

    def send_client(self, msg_type: str, body: list[tuple[int, str]]) -> str:
        raw = build_message(msg_type, SENDER, TARGET, self.client_seq, self.tick(), body)
        self.client_seq += 1
        self.messages.append(("CLIENT->B3", raw))
        return raw

    def send_server(self, msg_type: str, body: list[tuple[int, str]]) -> str:
        raw = build_message(msg_type, TARGET, SENDER, self.server_seq, self.tick(), body)
        self.server_seq += 1
        self.messages.append(("B3->CLIENT", raw))
        return raw


# ---------------------------------------------------------------------------
# Message builders — return body fields (tags after 52=SendingTime)
# ---------------------------------------------------------------------------

def logon_body(heartbeat: int = 30) -> list[tuple[int, str]]:
    return [
        (98, "0"),
        (108, str(heartbeat)),
        (141, "Y"),
        (553, CAU_USER),
        (554, CAU_PASS),
    ]


def heartbeat_body(test_req_id: str | None = None) -> list[tuple[int, str]]:
    return [(112, test_req_id)] if test_req_id else []


def logout_body(reason: str = "End of day session") -> list[tuple[int, str]]:
    return [(58, reason)]


def party_block() -> list[tuple[int, str]]:
    """Mandatory NoPartyIDs group for B3 EntryPoint."""
    return [
        (453, "1"),
        (448, SENDER),
        (447, "D"),
        (452, "1"),
    ]


def new_order_single_body(clordid: str, symbol: str, side: str, qty: int,
                          ord_type: str, price: float | None,
                          tif: str, transact_time: datetime,
                          handl_inst: str = "2") -> list[tuple[int, str]]:
    body: list[tuple[int, str]] = [
        (1, ACCOUNT),
        (11, clordid),
        (21, handl_inst),
        (38, str(qty)),
        (40, ord_type),
    ]
    if price is not None and ord_type in {"2", "4"}:
        body.append((44, fmt_price(price)))
    body += [
        (54, side),
        (55, symbol),
        (59, tif),
        (60, fmt_ts(transact_time)),
        (207, EXCHANGE),
    ]
    body += party_block()
    return body


def execution_report_body(order_id: str, clordid: str, exec_id: str,
                          exec_type: str, ord_status: str,
                          symbol: str, side: str, order_qty: int,
                          price: float, cum_qty: int, leaves_qty: int,
                          avg_px: float, last_qty: int = 0,
                          last_px: float = 0.0,
                          text: str | None = None) -> list[tuple[int, str]]:
    body: list[tuple[int, str]] = [
        (1, ACCOUNT),
        (6, fmt_price(avg_px)),
        (11, clordid),
        (14, str(cum_qty)),
        (17, exec_id),
        (37, order_id),
        (38, str(order_qty)),
        (39, ord_status),
        (44, fmt_price(price)),
        (54, side),
        (55, symbol),
        (150, exec_type),
        (151, str(leaves_qty)),
        (207, EXCHANGE),
        (336, "2"),
        (625, "0"),
    ]
    if exec_type in {"1", "2", "F"} and last_qty > 0:
        body += [(31, fmt_price(last_px)), (32, str(last_qty))]
    if text:
        body.append((58, text))
    return body


def cancel_request_body(orig_clordid: str, clordid: str, symbol: str,
                        side: str, qty: int,
                        transact_time: datetime) -> list[tuple[int, str]]:
    body = [
        (1, ACCOUNT),
        (11, clordid),
        (38, str(qty)),
        (41, orig_clordid),
        (54, side),
        (55, symbol),
        (60, fmt_ts(transact_time)),
        (207, EXCHANGE),
    ]
    body += party_block()
    return body


def cancel_replace_body(orig_clordid: str, clordid: str, symbol: str,
                        side: str, qty: int, ord_type: str, price: float,
                        tif: str, transact_time: datetime,
                        handl_inst: str = "2") -> list[tuple[int, str]]:
    body = [
        (1, ACCOUNT),
        (11, clordid),
        (21, handl_inst),
        (38, str(qty)),
        (40, ord_type),
        (41, orig_clordid),
        (44, fmt_price(price)),
        (54, side),
        (55, symbol),
        (59, tif),
        (60, fmt_ts(transact_time)),
        (207, EXCHANGE),
    ]
    body += party_block()
    return body


# ---------------------------------------------------------------------------
# Flow scenarios
# ---------------------------------------------------------------------------

def _order_id(n: int) -> str:
    return f"B3OID{n:06d}"


def _exec_id(n: int) -> str:
    return f"EXEC{n:06d}"


def _clord_id(date: datetime, n: int) -> str:
    return f"ORD-{date.strftime('%Y%m%d')}-{n:03d}"


def flow_1(session: Session) -> None:
    """Basic session with a partially-then-fully executed limit buy."""
    session.send_client("A", logon_body())
    session.send_server("A", logon_body())
    session.send_client("0", heartbeat_body())

    symbol = "PETR4"
    price = ASSETS[symbol]["price"]
    qty = 100
    clordid = _clord_id(session.clock, 1)

    session.send_client("D", new_order_single_body(
        clordid, symbol, "1", qty, "2", price, "0", session.clock))

    session.send_server("8", execution_report_body(
        _order_id(1), clordid, _exec_id(1),
        exec_type="0", ord_status="0",
        symbol=symbol, side="1", order_qty=qty,
        price=price, cum_qty=0, leaves_qty=qty, avg_px=0.0))

    session.send_server("8", execution_report_body(
        _order_id(1), clordid, _exec_id(2),
        exec_type="F", ord_status="1",
        symbol=symbol, side="1", order_qty=qty,
        price=price, cum_qty=40, leaves_qty=60, avg_px=price,
        last_qty=40, last_px=price))

    session.send_server("8", execution_report_body(
        _order_id(1), clordid, _exec_id(3),
        exec_type="2", ord_status="2",
        symbol=symbol, side="1", order_qty=qty,
        price=price, cum_qty=qty, leaves_qty=0, avg_px=price,
        last_qty=60, last_px=price))

    session.send_client("5", logout_body())


def flow_2(session: Session) -> None:
    """Order accepted then cancelled by the client."""
    session.send_client("A", logon_body())
    session.send_server("A", logon_body())

    symbol = "VALE3"
    price = ASSETS[symbol]["price"]
    qty = 200
    clordid = _clord_id(session.clock, 1)
    cxl_id = f"CXLREQ-{session.clock.strftime('%Y%m%d')}-001"

    session.send_client("D", new_order_single_body(
        clordid, symbol, "1", qty, "2", price, "0", session.clock))

    session.send_server("8", execution_report_body(
        _order_id(2), clordid, _exec_id(10),
        exec_type="0", ord_status="0",
        symbol=symbol, side="1", order_qty=qty,
        price=price, cum_qty=0, leaves_qty=qty, avg_px=0.0))

    session.send_client("F", cancel_request_body(
        clordid, cxl_id, symbol, "1", qty, session.clock))

    session.send_server("8", execution_report_body(
        _order_id(2), cxl_id, _exec_id(11),
        exec_type="4", ord_status="4",
        symbol=symbol, side="1", order_qty=qty,
        price=price, cum_qty=0, leaves_qty=0, avg_px=0.0,
        text="Cancelled by client request"))

    session.send_client("5", logout_body())


def flow_3(session: Session) -> None:
    """Order rejected by the matching engine."""
    session.send_client("A", logon_body())
    session.send_server("A", logon_body())

    symbol = "ITUB4"
    price = 1.00
    qty = 99999999
    clordid = _clord_id(session.clock, 1)

    session.send_client("D", new_order_single_body(
        clordid, symbol, "1", qty, "2", price, "0", session.clock))

    body = execution_report_body(
        "NONE", clordid, _exec_id(20),
        exec_type="8", ord_status="8",
        symbol=symbol, side="1", order_qty=qty,
        price=price, cum_qty=0, leaves_qty=0, avg_px=0.0,
        text="Order rejected: price outside trading band")
    body.append((103, "9"))
    session.send_server("8", body)

    session.send_client("5", logout_body())


def flow_4(session: Session) -> None:
    """Order accepted, then replaced with a new price."""
    session.send_client("A", logon_body())
    session.send_server("A", logon_body())

    symbol = "PETR4"
    price = ASSETS[symbol]["price"]
    new_price = price + 0.05
    qty = 500
    clordid = _clord_id(session.clock, 1)
    replace_id = _clord_id(session.clock, 2)

    session.send_client("D", new_order_single_body(
        clordid, symbol, "1", qty, "2", price, "0", session.clock))

    session.send_server("8", execution_report_body(
        _order_id(3), clordid, _exec_id(30),
        exec_type="0", ord_status="0",
        symbol=symbol, side="1", order_qty=qty,
        price=price, cum_qty=0, leaves_qty=qty, avg_px=0.0))

    session.send_client("G", cancel_replace_body(
        clordid, replace_id, symbol, "1", qty, "2", new_price, "0",
        session.clock))

    session.send_server("8", execution_report_body(
        _order_id(3), replace_id, _exec_id(31),
        exec_type="5", ord_status="5",
        symbol=symbol, side="1", order_qty=qty,
        price=new_price, cum_qty=0, leaves_qty=qty, avg_px=0.0))

    session.send_client("5", logout_body())


def flow_5(session: Session, total: int = 50) -> None:
    """High-volume mixed flow: orders, fills, 3 cancels, 2 rejects, heartbeats."""
    rng = random.Random(42)
    session.send_client("A", logon_body())
    session.send_server("A", logon_body())

    cancel_slots = {12, 28, 41}
    reject_slots = {18, 35}

    open_orders: list[dict] = []
    order_counter = 0
    exec_counter = 100
    cxl_counter = 0

    produced = 0
    while produced < total:
        slot = produced + 1

        if slot in cancel_slots and open_orders:
            target = open_orders.pop(rng.randrange(len(open_orders)))
            cxl_counter += 1
            cxl_id = f"CXLREQ-{session.clock.strftime('%Y%m%d')}-{cxl_counter:03d}"
            session.send_client("F", cancel_request_body(
                target["clordid"], cxl_id, target["symbol"], target["side"],
                target["qty"], session.clock))
            produced += 1
            exec_counter += 1
            session.send_server("8", execution_report_body(
                target["order_id"], cxl_id, _exec_id(exec_counter),
                exec_type="4", ord_status="4",
                symbol=target["symbol"], side=target["side"],
                order_qty=target["qty"], price=target["price"],
                cum_qty=target["cum_qty"],
                leaves_qty=0, avg_px=target["avg_px"]))
            produced += 1

        elif slot in reject_slots:
            order_counter += 1
            symbol = rng.choice(list(ASSETS.keys()))
            qty = 100000000
            price = 0.01
            clordid = _clord_id(session.clock, order_counter + 500)
            session.send_client("D", new_order_single_body(
                clordid, symbol, rng.choice(["1", "2"]), qty, "2",
                price, "0", session.clock))
            produced += 1
            exec_counter += 1
            session.send_server("8", execution_report_body(
                "NONE", clordid, _exec_id(exec_counter),
                exec_type="8", ord_status="8",
                symbol=symbol, side="1", order_qty=qty,
                price=price, cum_qty=0, leaves_qty=0, avg_px=0.0,
                text="Order rejected by risk engine"))
            produced += 1

        else:
            order_counter += 1
            symbol = rng.choice(list(ASSETS.keys()))
            ref_price = ASSETS[symbol]["price"]
            price = round(ref_price * rng.uniform(0.98, 1.02), 2)
            qty = rng.choice([100, 200, 300, 500, 1000])
            side = rng.choice(["1", "2"])
            clordid = _clord_id(session.clock, order_counter)

            session.send_client("D", new_order_single_body(
                clordid, symbol, side, qty, "2", price, "0", session.clock))
            produced += 1

            order_id = _order_id(order_counter)
            exec_counter += 1
            session.send_server("8", execution_report_body(
                order_id, clordid, _exec_id(exec_counter),
                exec_type="0", ord_status="0",
                symbol=symbol, side=side, order_qty=qty,
                price=price, cum_qty=0, leaves_qty=qty, avg_px=0.0))
            produced += 1

            if produced < total and rng.random() < 0.7:
                fill_qty = qty if rng.random() < 0.6 else qty // 2
                exec_counter += 1
                cum_qty = fill_qty
                leaves = qty - cum_qty
                ord_status = "2" if leaves == 0 else "1"
                exec_type = "2" if leaves == 0 else "F"
                session.send_server("8", execution_report_body(
                    order_id, clordid, _exec_id(exec_counter),
                    exec_type=exec_type, ord_status=ord_status,
                    symbol=symbol, side=side, order_qty=qty,
                    price=price, cum_qty=cum_qty, leaves_qty=leaves,
                    avg_px=price, last_qty=fill_qty, last_px=price))
                produced += 1

                if leaves > 0:
                    open_orders.append({
                        "clordid": clordid, "order_id": order_id,
                        "symbol": symbol, "side": side, "qty": qty,
                        "price": price, "cum_qty": cum_qty,
                        "avg_px": price,
                    })
            else:
                open_orders.append({
                    "clordid": clordid, "order_id": order_id,
                    "symbol": symbol, "side": side, "qty": qty,
                    "price": price, "cum_qty": 0, "avg_px": 0.0,
                })

        if produced > 0 and produced % 10 == 0 and produced < total:
            session.send_client("0", heartbeat_body())
            produced += 1

    session.send_client("5", logout_body())


FLOWS = {
    1: ("Basic session with partial + full fill", flow_1),
    2: ("Order accepted then cancelled",          flow_2),
    3: ("Order rejected by exchange",             flow_3),
    4: ("Order accepted then replaced",           flow_4),
    5: ("High-volume mixed stress flow",          flow_5),
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def render(messages: Iterable[tuple[str, str]], readable: bool,
           annotate: bool) -> str:
    out_lines: list[str] = []
    for direction, raw in messages:
        line = raw.replace(SOH, READABLE_SEP) if readable else raw
        if annotate:
            out_lines.append(f"# {direction}")
        out_lines.append(line)
    sep = "\n" if readable or annotate else ""
    return sep.join(out_lines) + (sep if out_lines else "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="FIX 4.4 message generator for B3 EntryPoint.")
    parser.add_argument("--flow", type=int, choices=sorted(FLOWS.keys()),
                        help="Flow number to generate (see --list-flows).")
    parser.add_argument("-r", "--readable", action="store_true",
                        help="Use '|' instead of SOH for visual inspection.")
    parser.add_argument("--annotate", action="store_true",
                        help="Prefix each message with a CLIENT->B3 / B3->CLIENT "
                             "comment line (forces line-separated output).")
    parser.add_argument("--volume", type=int, default=50,
                        help="Number of messages for flow 5 (default: 50).")
    parser.add_argument("--output", "-o", type=str,
                        help="Write output to file instead of stdout.")
    parser.add_argument("--list-flows", action="store_true",
                        help="List available flows and exit.")
    args = parser.parse_args(argv)

    if args.list_flows:
        for n, (desc, _) in FLOWS.items():
            print(f"  {n}: {desc}")
        return 0

    if args.flow is None:
        parser.error("--flow is required (use --list-flows to see options).")

    session = Session()
    _, builder = FLOWS[args.flow]
    if args.flow == 5:
        builder(session, args.volume)
    else:
        builder(session)

    output = render(session.messages, args.readable, args.annotate)

    if args.output:
        mode = "w" if args.readable or args.annotate else "wb"
        if mode == "wb":
            with open(args.output, "wb") as fh:
                fh.write(output.encode("ascii"))
        else:
            with open(args.output, "w", encoding="ascii") as fh:
                fh.write(output)
    else:
        if args.readable or args.annotate:
            sys.stdout.write(output)
        else:
            sys.stdout.buffer.write(output.encode("ascii"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
