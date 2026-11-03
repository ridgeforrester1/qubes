# /etc/profile.d/flatpak-proxy.sh
if [ "$(qubesdb-read /type 2>/dev/null)" = "TemplateVM" ]; then
    export http_proxy=http://127.0.0.1:8082
    export https_proxy=http://127.0.0.1:8082
fi
