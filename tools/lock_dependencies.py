"""Capture the installed runtime dependency closure, plus a complete dev lock."""

from importlib.metadata import distribution
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

roots = ["mcp", "httpx", "pydantic", "cryptography", "uvicorn", "starlette", "psycopg[binary]"]
queue = [Requirement(name) for name in roots]
seen = set()
versions = {}
while queue:
    req = queue.pop()
    name = canonicalize_name(req.name)
    extras = tuple(sorted(req.extras))
    if (name, extras) in seen:
        continue
    seen.add((name, extras))
    installed = distribution(req.name)
    versions[name] = installed.version
    for text in installed.requires or []:
        child = Requirement(text)
        if child.marker is None or any(
            child.marker.evaluate({"extra": extra}) for extra in ("", *extras)
        ):
            queue.append(child)
Path("requirements.lock").write_text(
    "# Runtime + PostgreSQL; resolved and tested on Python 3.14, macOS arm64.\n# Install the package with --no-deps after this file. Refresh intentionally.\n"
    + "".join(f"{name}=={version}\n" for name, version in sorted(versions.items()))
)
