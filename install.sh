#!/usr/bin/env bash
set -euo pipefail

source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
  printf '请以当前桌面用户运行此脚本，不要使用 sudo。系统安装请使用 .deb 包。\n' >&2
  exit 1
fi
if [[ ! -f "$source_dir/app.py" ]]; then
  printf '找不到 app.py，请在完整源码目录中运行安装脚本。\n' >&2
  exit 1
fi
if ! /usr/bin/python3 - <<'PY'
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, WebKit2
PY
then
  printf '\n请先安装运行依赖，然后重新运行本脚本：\n' >&2
  printf 'sudo apt install python3 python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 gstreamer1.0-plugins-good gstreamer1.0-libav\n' >&2
  exit 1
fi

# The XDG specification requires absolute base directories.
case ${XDG_DATA_HOME:-} in
  /*) data_home=$XDG_DATA_HOME ;;
  *) data_home="$HOME/.local/share" ;;
esac
# XDG_BIN_HOME is a convenient optional override; ~/.local/bin is the default.
case ${XDG_BIN_HOME:-} in
  /*) bin_home=$XDG_BIN_HOME ;;
  *) bin_home="$HOME/.local/bin" ;;
esac
app_dir="$data_home/netease-cloud-music/app"
desktop_dir="$data_home/applications"
icon_dir="$data_home/icons/hicolor/scalable/apps"
install -d "$app_dir/assets" "$bin_home" "$desktop_dir" "$icon_dir"
install -m 0644 "$source_dir/app.py" "$app_dir/app.py"
install -m 0644 "$source_dir/assets/"*.svg "$app_dir/assets/"
install -m 0644 "$source_dir/assets/netease-cloud-music.svg" "$icon_dir/netease-cloud-music.svg"
install -m 0755 "$source_dir/uninstall.sh" "$app_dir/uninstall.sh"

/usr/bin/python3 - "$source_dir/packaging/netease-cloud-music.desktop" "$app_dir" "$bin_home" "$desktop_dir" <<'PY'
from pathlib import Path
import shlex
import sys

template, app_dir, bin_home, desktop_dir = map(Path, sys.argv[1:])
launcher = bin_home / "netease-cloud-music"
launcher.write_text(
    '#!/bin/sh\nexec /usr/bin/python3 ' + shlex.quote(str(app_dir / "app.py")) + ' "$@"\n',
    encoding="utf-8",
)
launcher.chmod(0o755)

# Desktop Entry Exec has its own quoting rules, separate from shell quoting.
def exec_quote(value):
    value = value.replace("%", "%%")
    for character in ("\\", '"', "`", "$"):
        value = value.replace(character, "\\" + character)
    # Backslashes are escaped again by the Desktop Entry string parser.
    value = value.replace("\\", "\\\\")
    return '"' + value + '"'

desktop_text = template.read_text(encoding="utf-8")
desktop_text = desktop_text.replace("Exec=netease-cloud-music", "Exec=" + exec_quote(str(launcher)))
desktop_file = desktop_dir / "netease-cloud-music.desktop"
desktop_file.write_text(desktop_text, encoding="utf-8")
desktop_file.chmod(0o644)
PY

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$desktop_dir" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "$data_home/icons/hicolor" >/dev/null 2>&1 || true
fi
printf '已安装网易云音乐。请在应用菜单中搜索“网易云音乐”。\n直接启动：%q\n卸载脚本：%q\n' \
  "$bin_home/netease-cloud-music" "$app_dir/uninstall.sh"
