#!/usr/bin/env bash
# Download the latest epic games archive

# Fail on error
set -eo pipefail

if [ $# -gt 1 ] || [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
    echo "usage: $0 OUTPUT_DIR" >&2
    [ $# -gt 1 ] && exit 1 || exit
fi
OUTPUT_DIR="${1:-${OUTPUT_DIR:-.}}"

EPIC_GAMES_URL="${EPIC_GAMES_URL:-https://onlineservices.epicgames.com}"
EPIC_GAMES_SDK_TYPE="${EPIC_GAMES_SDK_TYPE:-sdk}"

# Get available SDK metadata
eos_info="$(curl --fail "${EPIC_GAMES_URL}/api/sdk")"

# Get the desired SDK's information
eos_sdk_info="$(jq ".results.${EPIC_GAMES_SDK_TYPE}" <<<"${eos_info}")"
test "${eos_sdk_info}" != null

eos_sdk_archive_id="$(jq -r .archive_id <<<"${eos_sdk_info}")"
test -n "${eos_sdk_archive_id}" && test "${eos_sdk_archive_id}" != null
eos_sdk_version="$(jq -r .version <<<"${eos_sdk_info}")"
test -n "${eos_sdk_version}" && test "${eos_sdk_version}" != null

# Download SDK's file
mkdir -p "$OUTPUT_DIR"

output_file="${OUTPUT_DIR%%/}/sdk-$eos_sdk_version.zip"
download_url="${EPIC_GAMES_URL}/api/sdk/download?archive_id=${eos_sdk_archive_id}&archive_type=${EPIC_GAMES_SDK_TYPE}"
wget -O "$output_file" "$download_url"

# Output structured download information
echo -n "${eos_sdk_version}|${output_file}|${download_url}"
