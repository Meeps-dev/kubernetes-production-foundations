#!/usr/bin/env python3
"""GET-only ingress checks, including original Day 94 user/post records.

Run inside an API Pod, with --base-url http://traefik.traefik-system.
Outside-to-inside host-port reachability is tested separately with host curl.
"""
import argparse
import json
import sys
from urllib.request import ProxyHandler, Request, build_opener
from urllib.error import HTTPError, URLError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-json", required=True)
    parser.add_argument("--base-url", default="http://traefik.traefik-system")
    args = parser.parse_args()
    fixture = json.loads(args.fixture_json)["fixture"]
    opener = build_opener(ProxyHandler({}))

    def get(path):
        req = Request(args.base_url.rstrip("/") + path,
                      headers={"Host": "api.meeps.local"})
        with opener.open(req, timeout=10) as response:
            if response.status != 200:
                raise RuntimeError(f"Unexpected HTTP status: {response.status}")
            return json.load(response)

    assert get("/") == {"status": "API is running"}
    assert get("/health") == {"status": "healthy"}
    assert get("/ready") == {"status": "ready"}
    user, post = fixture["user"], fixture["post"]
    users = get("/users/")
    posts = get(f"/posts/users/{user['id']}")
    assert any(all(row.get(k) == v for k, v in user.items()) for row in users), "Original user changed/missing"
    assert any(all(row.get(k) == v for k, v in post.items()) for row in posts), "Original post changed/missing"
    print(json.dumps({"result": "PASS", "mode": "GET-only",
                      "route_host": "api.meeps.local", "user_id": user["id"],
                      "post_id": post["id"],
                      "checks": ["root", "health", "ready", "original_user", "original_post"]}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, KeyError, ValueError, TypeError, RuntimeError, HTTPError, URLError) as exc:
        print(f"INGRESS TEST FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
