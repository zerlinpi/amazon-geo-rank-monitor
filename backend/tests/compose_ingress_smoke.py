"""Exercise both forwarding trust boundaries against isolated CI containers."""

import argparse
import json
import time
import urllib.error
import urllib.request
from uuid import uuid4


def attempt(base_url, forwarded_ip):
    request = urllib.request.Request(
        f"{base_url}/api/v1/auth/login",
        data=json.dumps({
            "email": f"missing-{uuid4().hex}@example.com",
            "password": "ci-fixture-password-only",
        }).encode(),
        headers={"Content-Type": "application/json", "X-Forwarded-For": forwarded_ip},
    )
    try:
        urllib.request.urlopen(request, timeout=5)
        raise AssertionError("A nonexistent account must not authenticate")
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            assert json.load(exc)["error"]["message"] == "authentication rate limit exceeded"
        return exc.code


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--untrusted", action="store_true")
    args = parser.parse_args()
    # Keep this short sequence within one fixed rate-limit window.
    remaining = 60 - time.time() % 60
    if remaining < 8:
        time.sleep(remaining + 0.1)
    if args.untrusted:
        # Rotating a forged header must not rotate the actual caller's bucket.
        actual = [attempt(args.base_url, f"198.51.100.{i}") for i in (20, 21, 22)]
        assert actual == [401, 401, 429], actual
    else:
        actual = [attempt(args.base_url, f"198.51.100.{i}") for i in (10, 10, 11, 10)]
        assert actual == [401, 401, 401, 429], actual
        try:
            urllib.request.urlopen(
                f"{args.base_url}/api/v1/auth/sso/callback"
                "?code=ci-private-callback-code&state=ci-private-callback-state",
                timeout=5,
            )
        except urllib.error.HTTPError:
            pass
    print("Ingress trust and authentication limit checks passed")


if __name__ == "__main__":
    main()
