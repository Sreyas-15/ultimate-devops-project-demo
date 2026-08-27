#!/usr/bin/env python3
"""
Build and push all microservice Docker images from src/.
- Detects services by presence of a Dockerfile.
- Determines correct build context (repo root vs service dir) by inspecting COPY paths.
- Tags images as sreyastendulkar/<service>:v1
- Pushes ALL images only if every build succeeds.
"""

import os
import subprocess
import sys
from pathlib import Path

DOCKER_USERNAME = "sreyastendulkar"
IMAGE_TAG = "v1"
REPO_ROOT = Path(__file__).resolve().parent  # script must live at repo root

SRC_DIR = REPO_ROOT / "src"

# Build args from .env that some Dockerfiles require
BUILD_ARGS = {
    "OPENTELEMETRY_CPP_VERSION": "1.23.0",
    "OTEL_JAVA_AGENT_VERSION": "2.20.1",
}


def find_services():
    """Find all services under src/ that have a Dockerfile (top-level or one level deeper)."""
    services = []
    for entry in sorted(SRC_DIR.iterdir()):
        if not entry.is_dir():
            continue
        # Check for Dockerfile at src/<service>/Dockerfile
        dockerfile = entry / "Dockerfile"
        if dockerfile.is_file():
            services.append((entry.name, dockerfile))
            continue
        # Also check one level deeper (e.g. src/cart/src/Dockerfile)
        for sub in entry.iterdir():
            if sub.is_dir():
                df = sub / "Dockerfile"
                if df.is_file():
                    services.append((entry.name, df))
                    break
    return services


def needs_repo_root_context(dockerfile: Path) -> bool:
    """Return True if the Dockerfile references ./src/ or /src/ paths (needs repo root as context)."""
    content = dockerfile.read_text(encoding="utf-8", errors="replace")
    # If COPY/mount instructions reference ./src/ or /src/ or ./pb/ or /pb/, it needs repo root
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if any(pattern in stripped for pattern in ["./src/", "/src/", "./pb/", "/pb/"]):
            return True
    return False


def build_image(service_name: str, dockerfile: Path) -> str:
    """Build a Docker image for the service. Returns the full image tag."""
    image_tag = f"{DOCKER_USERNAME}/{service_name}:{IMAGE_TAG}"
    repo_root_ctx = needs_repo_root_context(dockerfile)

    if repo_root_ctx:
        context = str(REPO_ROOT)
    else:
        context = str(dockerfile.parent)

    cmd = [
        "docker", "build",
        "-f", str(dockerfile),
        "-t", image_tag,
    ]

    # Add build args
    for arg_name, arg_value in BUILD_ARGS.items():
        cmd.extend(["--build-arg", f"{arg_name}={arg_value}"])

    cmd.append(context)

    print(f"\n{'='*60}")
    print(f"Building: {image_tag}")
    print(f"  Dockerfile : {dockerfile.relative_to(REPO_ROOT)}")
    print(f"  Context    : {'repo root' if repo_root_ctx else dockerfile.parent.relative_to(REPO_ROOT)}")
    print(f"  Command    : {' '.join(cmd)}")
    print(f"{'='*60}")

    result = subprocess.run(cmd, cwd=str(REPO_ROOT))
    if result.returncode != 0:
        print(f"FAILED to build {image_tag}", file=sys.stderr)
        return ""
    return image_tag


def push_images(tags: list[str]):
    """Push all images to Docker Hub."""
    print(f"\n{'='*60}")
    print(f"All {len(tags)} images built successfully. Pushing...")
    print(f"{'='*60}")
    for tag in tags:
        print(f"\nPushing: {tag}")
        result = subprocess.run(["docker", "push", tag])
        if result.returncode != 0:
            print(f"FAILED to push {tag}", file=sys.stderr)
            sys.exit(1)
    print(f"\nAll {len(tags)} images pushed successfully!")


def main():
    services = find_services()
    if not services:
        print("No services with Dockerfiles found under src/")
        sys.exit(1)

    print(f"Discovered {len(services)} services with Dockerfiles:")
    for name, df in services:
        print(f"  - {name:25s} {df.relative_to(REPO_ROOT)}")

    # Build phase — collect successful tags
    built_tags = []
    failed = []
    for name, dockerfile in services:
        tag = build_image(name, dockerfile)
        if tag:
            built_tags.append(tag)
        else:
            failed.append(name)

    # Summary
    print(f"\n{'='*60}")
    print(f"BUILD SUMMARY: {len(built_tags)} succeeded, {len(failed)} failed")
    if failed:
        print(f"Failed services: {', '.join(failed)}")
        print("Skipping push — not all builds succeeded.")
        sys.exit(1)

    # Push only if ALL builds succeeded
    push_images(built_tags)


if __name__ == "__main__":
    main()