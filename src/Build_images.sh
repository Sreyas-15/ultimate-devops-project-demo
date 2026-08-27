#!/usr/bin/env bash

set -u

if [ -f "../.env" ]; then
    set -a
    source "../.env"
    set +a
else
    echo "WARNING: .env file not found"
fi

# ============================================================
# Configuration
# ============================================================

DOCKER_USER="sreyastendulkar"
IMAGE_TAG="v1"

# ============================================================
# Colors / helpers
# ============================================================

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[SKIP]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# ============================================================
# Pre-checks
# ============================================================

if ! command -v docker >/dev/null 2>&1; then
    error "Docker is not installed or not available in PATH."
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    error "Docker engine is not running."
    exit 1
fi

if ! docker info 2>/dev/null | grep -q "Username: $DOCKER_USER"; then
    warning "You may not be logged into Docker Hub as $DOCKER_USER."
    log "Run: docker login"
fi

# ============================================================
# Phase 1 - Discover services
# ============================================================

declare -A SERVICE_DIR
declare -A SERVICE_STATUS
declare -A DEPENDENCIES

log "Scanning repository for Dockerfiles..."

for dir in */; do

    # Remove trailing /
    service="${dir%/}"

    # Ignore obvious non-service directories
    case "$service" in
        .git|.terraform|backend|modules|kubernetes|terraform)
            continue
            ;;
    esac

    if [[ -f "$dir/Dockerfile" ]]; then
        SERVICE_DIR["$service"]="$dir"
        SERVICE_STATUS["$service"]="pending"

        log "Found Dockerfile: $service"
    fi
done

if [[ ${#SERVICE_DIR[@]} -eq 0 ]]; then
    error "No Dockerfiles found."
    exit 1
fi

echo
log "Services discovered: ${#SERVICE_DIR[@]}"
echo

# ============================================================
# Phase 2 - Build dependency map
#
# We use Docker Compose if a compose file exists.
# docker compose config converts YAML into JSON, which avoids
# depending on yq/Python YAML libraries.
# ============================================================

COMPOSE_FILE=""

if [[ -f "compose.yaml" ]]; then
    COMPOSE_FILE="compose.yaml"
elif [[ -f "compose.yml" ]]; then
    COMPOSE_FILE="compose.yml"
elif [[ -f "docker-compose.yaml" ]]; then
    COMPOSE_FILE="docker-compose.yaml"
elif [[ -f "docker-compose.yml" ]]; then
    COMPOSE_FILE="docker-compose.yml"
fi

if [[ -n "$COMPOSE_FILE" ]]; then

    log "Found Compose file: $COMPOSE_FILE"
    log "Building dependency map..."

    COMPOSE_JSON=$(docker compose -f "$COMPOSE_FILE" config --format json 2>/dev/null)

    if [[ -z "$COMPOSE_JSON" ]]; then
        warning "Could not read Compose configuration."
        warning "Continuing without dependency information."
    else

        # Requires Python 3, which is normally available in a
        # development environment.
        while IFS='|' read -r service dependency; do

            [[ -z "$service" ]] && continue
            [[ -z "$dependency" ]] && continue

            # Only care about services that we actually found
            # Dockerfiles for.
            if [[ -n "${SERVICE_DIR[$service]+x}" ]]; then
                DEPENDENCIES["$service"]+="${dependency} "
            fi

        done < <(
            printf '%s\n' "$COMPOSE_JSON" |
            python3 -c '
import sys
import json

data = json.load(sys.stdin)

for service_name, service in data.get("services", {}).items():
    deps = service.get("depends_on", {})

    if isinstance(deps, dict):
        for dependency in deps.keys():
            print(f"{service_name}|{dependency}")

    elif isinstance(deps, list):
        for dependency in deps:
            print(f"{service_name}|{dependency}")
'
        )
    fi

else
    warning "No Compose file found."
    warning "No runtime dependency map will be used."
fi

# ============================================================
# Print dependency map
# ============================================================

echo
echo "============================================================"
echo "DEPENDENCY MAP"
echo "============================================================"

for service in "${!SERVICE_DIR[@]}"; do

    deps="${DEPENDENCIES[$service]-}"

    if [[ -n "$deps" ]]; then
        echo "$service -> $deps"
    else
        echo "$service -> none"
    fi

done

echo "============================================================"
echo

# ============================================================
# Dependency checking
# ============================================================

can_build() {

    local service="$1"
    local deps="${DEPENDENCIES[$service]-}"

    for dependency in $deps; do

        # If dependency isn't one of our Dockerfile services,
        # it may be an external image/service.
        if [[ -z "${SERVICE_DIR[$dependency]+x}" ]]; then
            continue
        fi

        # Dependency failed
        if [[ "${SERVICE_STATUS[$dependency]}" == "failed" ]]; then
            return 1
        fi

        # Dependency skipped
        if [[ "${SERVICE_STATUS[$dependency]}" == "skipped" ]]; then
            return 1
        fi

        # Dependency hasn't been built yet
        if [[ "${SERVICE_STATUS[$dependency]}" != "success" ]]; then
            return 2
        fi

    done

    return 0
}

# ============================================================
# Build function
# ============================================================

build_service() {

    local service="$1"
    local dir="${SERVICE_DIR[$service]}"
    local image="${DOCKER_USER}/${service}:${IMAGE_TAG}"

    echo
    echo "============================================================"
    log "Building: $service"
    log "Directory: $dir"
    log "Image: $image"
    echo "============================================================"

    SERVICE_STATUS["$service"]="building"

    if docker build \
        --tag "$image" \
        --file "$dir/Dockerfile" \
        --build-arg "OTEL_JAVA_AGENT_VERSION=$OTEL_JAVA_AGENT_VERSION" \
        --build-arg "OPENTELEMETRY_CPP_VERSION=$OPENTELEMETRY_CPP_VERSION" \
        ..; then

        success "Build successful: $image"

    else

        error "Build FAILED: $service"
        SERVICE_STATUS["$service"]="failed"
        return 1
    fi

    echo
    log "Pushing $image..."

    if docker push "$image"; then

        success "Push successful: $image"
        SERVICE_STATUS["$service"]="success"

    else

        error "Push FAILED: $image"
        SERVICE_STATUS["$service"]="failed"
        return 1
    fi

    return 0
}

# ============================================================
# Phase 3 - Dependency-aware build
# ============================================================

log "Starting dependency-aware build..."

remaining=1

while [[ "$remaining" -eq 1 ]]; do

    remaining=0
    progress=0

    for service in "${!SERVICE_DIR[@]}"; do

        status="${SERVICE_STATUS[$service]}"

        # Already processed
        if [[ "$status" != "pending" ]]; then
            continue
        fi

        remaining=1

        can_build "$service"
        result=$?

        # Dependencies haven't finished yet
        if [[ "$result" -eq 2 ]]; then
            continue
        fi

        # A dependency failed
        if [[ "$result" -eq 1 ]]; then
            warning "$service skipped because one of its dependencies failed."
            SERVICE_STATUS["$service"]="skipped"
            progress=1
            continue
        fi

        # No unresolved dependencies
        build_service "$service"
        progress=1

    done

    # Prevent infinite loop if a circular dependency exists
    if [[ "$progress" -eq 0 && "$remaining" -eq 1 ]]; then

        error "Dependency cycle or unresolved dependency detected."

        for service in "${!SERVICE_DIR[@]}"; do
            if [[ "${SERVICE_STATUS[$service]}" == "pending" ]]; then
                error "Unable to resolve: $service"
            fi
        done

        break
    fi

done

# ============================================================
# Final summary
# ============================================================

echo
echo
echo "============================================================"
echo "BUILD SUMMARY"
echo "============================================================"

for service in "${!SERVICE_DIR[@]}"; do

    status="${SERVICE_STATUS[$service]}"

    case "$status" in
        success)
            success "$service -> ${DOCKER_USER}/${service}:${IMAGE_TAG}"
            ;;

        failed)
            error "$service -> FAILED"
            ;;

        skipped)
            warning "$service -> SKIPPED"
            ;;

        *)
            warning "$service -> $status"
            ;;
    esac

done

echo "============================================================"