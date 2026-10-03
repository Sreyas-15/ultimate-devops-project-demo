#!/usr/bin/env python3
"""
Build and push all microservice Docker images from src/.
- Detects services by presence of a Dockerfile.
- Determines correct build context (repo root vs service dir) by inspecting COPY paths.
- Tags images as sreyastendulkar/<service>:v1
- Pushes ALL images only if every build succeeds.
"""

import json
import subprocess
import sys
from pathlib import Path

DOCKER_USERNAME = "sreyastendulkar"
IMAGE_TAG = "v1"
REPO_ROOT = Path(__file__).resolve().parent  # script must live at repo root

SRC_DIR = REPO_ROOT / "src"

# Build args from .env that some Dockerfiles require
# this method untill we develop a dynamic mechanism of loading the env variables in workspace
BUILD_ARGS = {
    "OPENTELEMETRY_CPP_VERSION": "1.23.0",
    "OTEL_JAVA_AGENT_VERSION": "2.20.1",
}

# Load service context mapping from JSON
SERVICE_CONTEXT_FILE = REPO_ROOT / "service_context.json"
if not SERVICE_CONTEXT_FILE.is_file():
    print(f"ERROR: {SERVICE_CONTEXT_FILE} not found. Cannot determine build contexts.", file=sys.stderr)
    sys.exit(1)
with open(SERVICE_CONTEXT_FILE, "r") as f:
    SERVICE_CONTEXT = json.load(f)


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


def build_image(service_name: str, dockerfile: Path) -> str:
    """Build a Docker image for the service. Returns the full image tag."""
    image_tag = f"{DOCKER_USERNAME}/{service_name}:{IMAGE_TAG}"
    ctx_type = SERVICE_CONTEXT.get(service_name, "root")
    context = str(dockerfile.parent) if ctx_type == "local" else str(REPO_ROOT)

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
    print(f"  Context    : {'repo root' if ctx_type == 'root' else dockerfile.parent.relative_to(REPO_ROOT)}")
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
    for tag in tags:
        print(f"\nPushed: {tag}")        

def main():
    services = find_services()  # collate a list of services its an estimation from dockerfile and should have entry in json file for services
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
        if len(failed)==1 and failed[0]=='currency':    #handling the currency code failure here
                push_images(built_tags)
        else:
                print("Skipping push — not all builds succeeded.")
               
    else:
        # Push only if ALL builds succeeded to handle the edge 
        push_images(built_tags)


if __name__ == "__main__":
    main()