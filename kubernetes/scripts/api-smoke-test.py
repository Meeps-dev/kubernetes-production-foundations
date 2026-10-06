#!/usr/bin/env python3
"""Create/read lab fixtures, or verify the same fixtures without recreating them.

Run using Python inside an API container; no host Python dependencies are needed.
Only generated test records are written. Verification mode performs GETs only.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("create", "verify"))
    parser.add_argument("--base-url", default="http://meeps-api")
    parser.add_argument("--fixture-json", help="The JSON output from create mode.")
    args = parser.parse_args()
    if args.mode == "verify" and not args.fixture_json:
        parser.error("verify requires --fixture-json; it must not recreate records")

    base = args.base_url.rstrip("/")
    opener = build_opener(ProxyHandler({}))

    def request(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        body = json.dumps(payload).encode() if payload is not None else None
        req = Request(base + path, data=body, method=method,
                      headers={"Content-Type": "application/json"})
        try:
            with opener.open(req, timeout=10) as response:
                return json.load(response)
        except HTTPError as exc:
            raise RuntimeError(f"{method} {path}: HTTP {exc.code}; inspect API logs") from None
        except URLError as exc:
            raise RuntimeError(f"{method} {path}: connection failed ({exc.reason})") from None

    if request("GET", "/").get("status") != "API is running":
        raise RuntimeError("Unexpected root response")
    if request("GET", "/health").get("status") != "healthy":
        raise RuntimeError("Unexpected health response")

    paths = request("GET", "/openapi.json")["paths"]
    for path in ("/users/", "/posts/users/{user_id}"):
        if not {"get", "post"}.issubset(paths.get(path, {})):
            raise RuntimeError(f"Image route contract differs from the reviewed source: {path}")

    if args.mode == "create":
        marker = uuid.uuid4().hex[:12]
        user = request("POST", "/users/", {
            "name": "Day 94 Kubernetes User",
            "email": f"day94-{marker}@example.test",
        })
        post = request("POST", f"/posts/users/{user['id']}", {
            "title": f"Day 94 persistence check {marker}",
            "content": "This record must remain readable after an API Pod is replaced.",
        })
        if post.get("user_id") != user["id"]:
            raise RuntimeError("Created post is associated with the wrong user")
        fixture = {"user": user, "post": post}
    else:
        fixture = json.loads(args.fixture_json)["fixture"]

    user, post = fixture["user"], fixture["post"]
    users = request("GET", "/users/")
    posts = request("GET", f"/posts/users/{user['id']}")
    if not any(all(row.get(k) == v for k, v in user.items()) for row in users):
        raise RuntimeError("Original user record was not found unchanged")
    if not any(all(row.get(k) == v for k, v in post.items()) for row in posts):
        raise RuntimeError("Original post record was not found unchanged")

    print(json.dumps({
        "result": "PASS", "mode": args.mode, "base_url": base,
        "checks": ["root", "health", "user_read", "post_read"],
        "fixture": fixture,
    }, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, KeyError, TypeError) as exc:
        print(f"SMOKE TEST FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
