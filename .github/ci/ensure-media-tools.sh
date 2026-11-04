#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Install ffmpeg (libx264, libass, libvmaf) and espeak-ng with a pt-BR voice.
#
# Ubuntu 24.04's ffmpeg package is built with libx264 and libass and without
# libvmaf. When a probe fails, this script downloads a pinned GPL static build
# from BtbN/FFmpeg-Builds, checks its SHA-256, and puts that bin directory
# first on PATH. The binary is not committed. Megila does not vendor ffmpeg
# (ADR 0002); CI calls it as an external program.
#
# Append the selected bin directory to $GITHUB_PATH when that variable is set,
# which is how later GitHub Actions steps see the static build.

set -euo pipefail

FFMPEG_TAG="autobuild-2026-11-04-12-51"
FFMPEG_AMD64_ASSET="ffmpeg-n8.1.3-34-ga35157abb9-linux64-gpl-8.1.tar.xz"
FFMPEG_AMD64_SHA256="0fc51331600b02730e6d63485ac7e3cd203bdeeb13216cd78c8844aeb9277fb8"
FFMPEG_ARM64_ASSET="ffmpeg-n8.1.3-34-ga35157abb9-linuxarm64-gpl-8.1.tar.xz"
FFMPEG_ARM64_SHA256="e4d93d4b858a341cf29cbcd0ce2e31271bba67018b27ff4ef3c2e1683f76b810"

CACHE_ROOT="${MEGILA_FFMPEG_CACHE:-${HOME}/.cache/megila/ffmpeg}"

usage() {
  echo "usage: ensure-media-tools.sh [--check|--static-only]" >&2
}

has_field() {
  local name="$1"
  awk -v wanted="${name}" '$2 == wanted { found = 1 } END { exit found ? 0 : 1 }'
}

ffmpeg_features_ok() {
  command -v ffmpeg >/dev/null 2>&1 || return 1
  command -v ffprobe >/dev/null 2>&1 || return 1
  ffmpeg -hide_banner -encoders 2>/dev/null | has_field libx264
  ffmpeg -hide_banner -filters 2>/dev/null | has_field ass
  ffmpeg -hide_banner -filters 2>/dev/null | has_field libvmaf
}

espeak_ok() {
  command -v espeak-ng >/dev/null 2>&1 || return 1
  espeak-ng --voices 2>/dev/null | has_field pt-br
}

tools_ok() {
  ffmpeg_features_ok && espeak_ok
}

run_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}

apt_install() {
  # Hosted runners often start apt in the background. apt-get waits on that
  # lock with no deadline, so bound both the lists lock and the dpkg lock.
  run_root flock -w 180 /var/lib/apt/lists/lock \
    flock -w 180 /var/lib/dpkg/lock-frontend \
    apt-get update
  run_root flock -w 180 /var/lib/apt/lists/lock \
    flock -w 180 /var/lib/dpkg/lock-frontend \
    apt-get install -y ffmpeg espeak-ng
}

select_static() {
  if [ -n "${MEGILA_FFMPEG_URL:-}" ] || [ -n "${MEGILA_FFMPEG_SHA256:-}" ]; then
    if [ -z "${MEGILA_FFMPEG_URL:-}" ] || [ -z "${MEGILA_FFMPEG_SHA256:-}" ]; then
      echo "set both MEGILA_FFMPEG_URL and MEGILA_FFMPEG_SHA256" >&2
      exit 1
    fi
    STATIC_URL="${MEGILA_FFMPEG_URL}"
    STATIC_SHA="${MEGILA_FFMPEG_SHA256}"
    return
  fi
  case "$(uname -m)" in
    x86_64)
      STATIC_URL="https://github.com/BtbN/FFmpeg-Builds/releases/download/${FFMPEG_TAG}/${FFMPEG_AMD64_ASSET}"
      STATIC_SHA="${FFMPEG_AMD64_SHA256}"
      ;;
    aarch64 | arm64)
      STATIC_URL="https://github.com/BtbN/FFmpeg-Builds/releases/download/${FFMPEG_TAG}/${FFMPEG_ARM64_ASSET}"
      STATIC_SHA="${FFMPEG_ARM64_SHA256}"
      ;;
    *)
      echo "unsupported architecture for the static ffmpeg build: $(uname -m)" >&2
      exit 1
      ;;
  esac
}

activate_bin() {
  local bin_dir="$1"
  export PATH="${bin_dir}:${PATH}"
  hash -r
}

ffmpeg_features_in() {
  local bin_dir="$1"
  local old_path="${PATH}"
  local status
  activate_bin "${bin_dir}"
  if ffmpeg_features_ok; then
    status=0
  else
    status=1
  fi
  PATH="${old_path}"
  hash -r
  return "${status}"
}

install_static() {
  select_static
  local root="${CACHE_ROOT}/${STATIC_SHA}"
  if [ -x "${root}/bin/ffmpeg" ] && [ -x "${root}/bin/ffprobe" ]; then
    if ffmpeg_features_in "${root}/bin"; then
      activate_bin "${root}/bin"
      return 0
    fi
    rm -rf "${root}"
  fi

  local work archive found bin_dir
  work="$(mktemp -d)"
  archive="${work}/ffmpeg.tar.xz"
  curl --fail --silent --show-error --location \
    --retry 5 --retry-delay 2 --retry-all-errors \
    --connect-timeout 20 --max-time 300 \
    --output "${archive}" "${STATIC_URL}"
  echo "${STATIC_SHA}  ${archive}" | sha256sum --check
  tar --extract --xz --file "${archive}" --directory "${work}"
  found="$(find "${work}" -type f -path '*/bin/ffmpeg' -print -quit)"
  if [ -z "${found}" ] || [ ! -f "$(dirname "${found}")/ffprobe" ]; then
    echo "static ffmpeg archive is missing bin/ffmpeg or bin/ffprobe" >&2
    rm -rf "${work}"
    exit 1
  fi
  bin_dir="$(dirname "${found}")"
  mkdir -p "${root}/bin"
  install -m 0755 "${bin_dir}/ffmpeg" "${root}/bin/ffmpeg"
  install -m 0755 "${bin_dir}/ffprobe" "${root}/bin/ffprobe"
  rm -rf "${work}"
  activate_bin "${root}/bin"
  if ! ffmpeg_features_ok; then
    echo "static ffmpeg does not provide libx264, the ass filter, and libvmaf" >&2
    exit 1
  fi
}

first_line() {
  local text="$1"
  printf '%s\n' "${text%%$'\n'*}"
}

report() {
  local ffmpeg_version espeak_version
  ffmpeg_version="$(ffmpeg -hide_banner -version 2>&1)"
  espeak_version="$(espeak-ng --version 2>&1)"
  echo "ffmpeg: $(command -v ffmpeg)"
  first_line "${ffmpeg_version}"
  echo "ffprobe: $(command -v ffprobe)"
  echo "espeak-ng: $(command -v espeak-ng)"
  first_line "${espeak_version}"
  echo "libx264, libass (ass filter), and libvmaf: present"
}

record_github_path() {
  if [ -n "${GITHUB_PATH:-}" ]; then
    dirname "$(command -v ffmpeg)" >> "${GITHUB_PATH}"
  fi
}

fail_gap() {
  echo "ffmpeg must provide libx264, libass (ass filter), and libvmaf; espeak-ng must provide the pt-br voice" >&2
  exit 1
}

if [ "$#" -gt 1 ]; then
  usage
  exit 2
fi

mode="${1:-}"
case "${mode}" in
  --check)
    if tools_ok; then
      report
      record_github_path
      exit 0
    fi
    fail_gap
    ;;
  --static-only)
    if ! ffmpeg_features_ok; then
      install_static
    fi
    ;;
  "")
    if ! tools_ok; then
      apt_install
    fi
    if ! ffmpeg_features_ok; then
      install_static
    fi
    ;;
  *)
    usage
    exit 2
    ;;
esac

if ! tools_ok; then
  echo "required media tools are still unavailable" >&2
  exit 1
fi
record_github_path
report
