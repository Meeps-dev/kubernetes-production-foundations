#!/usr/bin/env python3
"""Read Traefik JSON logs on stdin and verify only ready backends served the drill."""
import argparse
import json
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--marker", required=True)
parser.add_argument("--bad-ip", required=True)
parser.add_argument("--ready-ips", required=True)
parser.add_argument("--expected", type=int, default=20)
args = parser.parse_args()
allowed = {ip + ":8000" for ip in args.ready_ips.split()}
records = []
for line in sys.stdin:
    try:
        row = json.loads(line)
    except json.JSONDecodeError:
        continue
    # A unique, non-secret lab header is the primary correlator. Header spelling
    # can be canonicalized by Go. RequestPath is a fallback for log configurations
    # that include the query string.
    marker_header = next((value for key, value in row.items()
                          if key.lower() == "request_x-meeps-drill"), None)
    matches = marker_header == args.marker or args.marker in str(row.get("RequestPath", ""))
    if matches and row.get("RequestHost") == "api.meeps.local":
        records.append(row)
if len(records) != args.expected:
    raise SystemExit(f"FAIL: Expected {args.expected} tagged access records; found {len(records)}.")
for row in records:
    if row.get("DownstreamStatus") != 200 or row.get("OriginStatus") != 200:
        raise SystemExit("FAIL: A tagged request was not a successful backend response.")
    address = row.get("ServiceAddr", "")
    if address == args.bad_ip + ":8000" or address not in allowed:
        raise SystemExit(f"FAIL: Unexpected/unready backend used: {address}")
print(json.dumps({
    "result": "PASS",
    "requests_checked": len(records),
    "backends_observed": sorted({row["ServiceAddr"] for row in records}),
    "unready_backend_excluded": args.bad_ip + ":8000",
    "scope": "Observed test requests only; not a guarantee of zero downtime.",
}, indent=2))
