#!/bin/sh

# abort if not in a template
if [ "$(qubesdb-read /type 2>/dev/null)" != "TemplateVM" ]; then
    echo "Not a template, skipping flatpak update" >&2
    exit 1
fi

export http_proxy=http://127.0.0.1:8082
export https_proxy=http://127.0.0.1:8082

flatpak upgrade -y --noninteractive
