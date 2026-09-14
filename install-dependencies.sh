#!/usr/bin/env bash
set -euo pipefail

for tool in apt-get apt-cache dpkg awk; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf '需要 Debian/Ubuntu 系统的 apt-get、apt-cache、dpkg 和 awk。\n' >&2
    exit 1
  fi
done
if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
  privilege=()
elif command -v sudo >/dev/null 2>&1; then
  privilege=(sudo)
else
  printf '安装系统依赖需要管理员权限，请以 root 运行此脚本。\n' >&2
  exit 1
fi

"${privilege[@]}" apt-get update
candidate() {
  LC_ALL=C apt-cache policy "$1" | awk '$1 == "Candidate:" { print $2; exit }'
}
at_least() {
  local version
  version=$(candidate "$1")
  [[ -n "$version" && "$version" != '(none)' ]] && dpkg --compare-versions "$version" ge "$2"
}
if at_least gir1.2-webkit2-4.1 2.36; then
  webkit_package=gir1.2-webkit2-4.1
elif at_least gir1.2-webkit2-4.0 2.28; then
  webkit_package=gir1.2-webkit2-4.0
else
  printf '当前软件源没有可用的 WebKitGTK 4.1（>= 2.36）或 4.0（>= 2.28）组件。\n' >&2
  printf '请检查发行版软件源与 CPU 架构；Ubuntu 可检查 universe 仓库是否启用。\n' >&2
  exit 1
fi
for requirement in 'python3 3.8' 'python3-gi 3.36' 'gir1.2-gtk-3.0 3.24'; do
  read -r package minimum <<< "$requirement"
  if ! at_least "$package" "$minimum"; then
    printf '当前软件源需要提供 %s >= %s。\n' "$package" "$minimum" >&2
    exit 1
  fi
done
packages=(python3 python3-gi gir1.2-gtk-3.0 "$webkit_package"
          ca-certificates librsvg2-common
          gstreamer1.0-plugins-base gstreamer1.0-plugins-good
          gstreamer1.0-libav gstreamer1.0-alsa)
# PulseAudio support is included in the good plugin set from 1.18 onward.
if ! at_least gstreamer1.0-plugins-good 1.18; then
  packages+=(gstreamer1.0-pulseaudio)
fi
printf '将安装 WebKitGTK 组件：%s\n' "$webkit_package"
"${privilege[@]}" apt-get install "${packages[@]}"
printf '依赖已安装。请在桌面用户会话中运行 bash install.sh。\n'
