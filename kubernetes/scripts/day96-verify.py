#!/usr/bin/env python3
"""GET-only checks. Run inside an API Pod; never creates fixture records."""
import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-json", required=True)
    parser.add_argument("--base-url", default="http://traefik.traefik-system")
    parser.add_argument("--expect-version")
    args = parser.parse_args()
    saved = json.loads(args.fixture_json)
    if saved.get("result") != "PASS":
        raise RuntimeError("Original fixture is not marked PASS")
    fixture = saved["fixture"]
    opener = build_opener(ProxyHandler({}))

    def get(path):
        request = Request(args.base_url.rstrip("/") + path,
                          headers={"Host": "api.meeps.local", "Connection": "close"})
        with opener.open(request, timeout=10) as response:
            if response.status != 200:
                raise RuntimeError("Unexpected HTTP status")
            return json.load(response)

    if get("/") != {"status": "API is running"}:
        raise RuntimeError("Root contract changed")
    if get("/health") != {"status": "healthy"}:
        raise RuntimeError("Health check failed")
    if get("/ready") != {"status": "ready"}:
        raise RuntimeError("Readiness check failed")
    identity = None
    if args.expect_version:
        identity = get("/version")
        if identity.get("version") != args.expect_version:
            raise RuntimeError("Wrong application release served")
    user, post = fixture["user"], fixture["post"]
    for expected, rows, label in (
        (user, get("/users/"), "user"),
        (post, get("/posts/users/{0}".format(user["id"])), "post"),
    ):
        if not any(all(row.get(k) == v for k, v in expected.items()) for row in rows):
            raise RuntimeError("Original {0} record changed or missing".format(label))
    print(json.dumps({"result": "PASS", "mode": "GET-only",
                      "base_url": args.base_url, "release": identity,
                      "user_id": user["id"], "post_id": post["id"]}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, KeyError, ValueError, TypeError, HTTPError, URLError) as error:
        print("DAY 96 API CHECK FAILED: {0}".format(error), file=sys.stderr)
        sys.exit(1)
