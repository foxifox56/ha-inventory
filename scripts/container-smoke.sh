#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

image_name="ha-inventory:container-smoke"
container_name="ha-inventory-container-smoke"
network_name="ha-inventory-smoke"
data_dir="$(mktemp -d)"
platform="${INVENTORY_SMOKE_PLATFORM:-}"
platform_args=()

if [[ -n "$platform" ]]; then
  platform_args+=(--platform "$platform")
fi

cleanup() {
  docker rm -f "$container_name" >/dev/null 2>&1 || true
  docker network rm "$network_name" >/dev/null 2>&1 || true
  rm -rf "$data_dir"
}
trap cleanup EXIT

if [[ -n "$platform" ]]; then
  docker buildx build "${platform_args[@]}" --load --tag "$image_name" ha_inventory
else
  docker build --tag "$image_name" ha_inventory
fi
docker network create --driver bridge --subnet 172.30.32.0/24 "$network_name" >/dev/null

start_app() {
  docker run "${platform_args[@]}" --detach \
    --name "$container_name" \
    --network "$network_name" \
    --ip 172.30.32.3 \
    --volume "$data_dir:/data" \
    "$image_name"
}

proxy_request() {
  docker run "${platform_args[@]}" --rm \
    --network "$network_name" \
    --ip "$1" \
    --entrypoint python3 \
    "$image_name" \
    -m backend.tests.container_smoke_client "$2" "http://172.30.32.3:8099"
}

start_app >/dev/null
proxy_request 172.30.32.2 wait
proxy_request 172.30.32.2 frontend
proxy_request 172.30.32.2 receipt-ocr
proxy_request 172.30.32.2 create
proxy_request 172.30.32.4 denied

docker rm --force "$container_name" >/dev/null
start_app >/dev/null
proxy_request 172.30.32.2 wait
proxy_request 172.30.32.2 read

echo "Container checks passed${platform:+ for $platform}: build, startup, ingress, local Tesseract deu+eng OCR, receipt parsing, idempotent stock booking, undo, history, and /data persistence."
