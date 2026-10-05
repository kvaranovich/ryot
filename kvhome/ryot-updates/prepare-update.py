#!/usr/bin/env python3
"""Prepare an isolated Ryot update candidate without changing the source checkout."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def git(repo, *args, data=None, check=True):
    return subprocess.run(
        ["git", "-C", str(repo), *args], input=data, capture_output=True, check=check
    )


def commit(repo, ref):
    return git(repo, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}").stdout.decode().strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--fork", required=True)
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    if output == source or source in output.parents or output in source.parents:
        parser.error("Output must be separate from the source checkout")
    refs = {key: commit(source, getattr(args, key)) for key in ("base", "fork", "upstream")}
    paths = [":(exclude).github/**", ":(exclude)kvhome/**", ":(exclude)libs/generated/**"]
    patch = git(source, "diff", "--binary", refs["base"], refs["fork"], "--", *paths).stdout
    output.mkdir(parents=True, exist_ok=False)
    checkout = output / "source"
    subprocess.run(
        ["git", "clone", "--quiet", "--no-hardlinks", "--", str(source), str(checkout)],
        check=True, capture_output=True,
    )
    git(checkout, "checkout", "--quiet", "--detach", refs["upstream"])
    result = git(checkout, "apply", "--3way", "--index", "-", data=patch, check=False) if patch else None
    conflicts = git(checkout, "diff", "--name-only", "--diff-filter=U").stdout.decode().splitlines()
    failed = bool(conflicts or (result is not None and result.returncode))
    manifest = {
        **refs,
        "patch_sha256": hashlib.sha256(patch).hexdigest(),
        "status": "conflict" if failed else "prepared",
        "conflicts": conflicts,
        "regenerate": "libs/generated GraphQL operations before frontend validation",
    }
    if not failed:
        git(checkout, "diff", "--cached", "--check")
        manifest["tree"] = git(checkout, "write-tree").stdout.decode().strip()
    (output / "integration.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if failed:
        print("Update stopped before build: patch conflicts or could not be applied", file=sys.stderr)
        for name in conflicts:
            print(name, file=sys.stderr)
        return 2
    print("Update candidate prepared; build, tests and database preflight are still required")
    print(output / "integration.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
