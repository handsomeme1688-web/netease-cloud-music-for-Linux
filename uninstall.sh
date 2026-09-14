#!/usr/bin/env bash
set -euo pipefail

purge=false
if [[ $# -gt 1 ]] || [[ $# -eq 1 && $1 != --purge ]]; then
  printf '用法：%s [--purge]\n默认保留登录数据；--purge 同时删除本应用的登录数据、缓存和窗口配置。\n' "$0" >&2
  exit 2
fi
if [[ ${1:-} == --purge ]]; then
  purge=true
fi
if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
  printf '请以安装时的桌面用户运行此脚本，不要使用 sudo。\n' >&2
  exit 1
fi
case ${XDG_DATA_HOME:-} in
  /*) data_home=$XDG_DATA_HOME ;;
  *) data_home="$HOME/.local/share" ;;
esac
case ${XDG_CACHE_HOME:-} in
  /*) cache_home=$XDG_CACHE_HOME ;;
  *) cache_home="$HOME/.cache" ;;
esac
case ${XDG_CONFIG_HOME:-} in
  /*) config_home=$XDG_CONFIG_HOME ;;
  *) config_home="$HOME/.config" ;;
esac
case ${XDG_BIN_HOME:-} in
  /*) bin_home=$XDG_BIN_HOME ;;
  *) bin_home="$HOME/.local/bin" ;;
esac
data_dir="$data_home/netease-cloud-music"
app_dir="$data_dir/app"
rm -f -- "$bin_home/netease-cloud-music" \
  "$data_home/applications/netease-cloud-music.desktop" \
  "$data_home/icons/hicolor/scalable/apps/netease-cloud-music.svg" \
  "$app_dir/app.py" "$app_dir/assets/netease-cloud-music.svg" "$app_dir/uninstall.sh" \
  "$app_dir/assets/netease-window-minimize-symbolic.svg" \
  "$app_dir/assets/netease-window-maximize-symbolic.svg" \
  "$app_dir/assets/netease-window-restore-symbolic.svg" \
  "$app_dir/assets/netease-window-close-symbolic.svg"
rmdir -- "$app_dir/assets" 2>/dev/null || true
if "$purge"; then
  rm -f -- "$data_dir/cookies.sqlite" "$data_dir/cookies.sqlite-shm" "$data_dir/cookies.sqlite-wal" \
    "$config_home/netease-cloud-music/window.json" "$config_home/netease-cloud-music/window.tmp"
  rm -rf -- "$data_dir/webkit" "$cache_home/netease-cloud-music/webkit"
  rmdir -- "$config_home/netease-cloud-music" "$cache_home/netease-cloud-music" 2>/dev/null || true
  printf '已卸载用户安装的网易云音乐，并删除本应用登录数据、缓存和窗口配置。\n'
else
  printf '已卸载用户安装的网易云音乐；登录数据、缓存和窗口配置已保留。\n'
fi
rmdir -- "$app_dir" "$data_dir" 2>/dev/null || true
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$data_home/applications" >/dev/null 2>&1 || true
fi
