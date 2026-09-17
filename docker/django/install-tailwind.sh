#!/bin/sh
set -e

TAILWIND_VERSION="${TAILWIND_VERSION:-latest}"
TAILWIND_PATH="${TAILWIND_PATH:-tailwindcss}"

case "$(uname -s)" in
    Linux) os=linux ;;
    Darwin) os=macos ;;
    *) echo "unsupported OS: $(uname -s)" >&2; exit 1 ;;
esac

case "$(uname -m)" in
    x86_64) arch=x64 ;;
    aarch64 | arm64) arch=arm64 ;;
    *) echo "unsupported arch: $(uname -m)" >&2; exit 1 ;;
esac

if [ "$TAILWIND_VERSION" = "latest" ]; then
    url="https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-$os-$arch"
else
    url="https://github.com/tailwindlabs/tailwindcss/releases/download/v$TAILWIND_VERSION/tailwindcss-$os-$arch"
fi

if command -v curl >/dev/null; then
    curl -fsSL -o "$TAILWIND_PATH" "$url"
else
    python3 -c "import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])" "$url" "$TAILWIND_PATH"
fi
chmod +x "$TAILWIND_PATH"
