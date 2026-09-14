#!/usr/bin/env bash
set -euo pipefail
umask 022

source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
output_dir=${1:-"$source_dir/dist"}
version=1.0.1
package_name=netease-cloud-music-webkit

for command in dpkg-deb tar gzip install python3 mkdir mktemp cp du cut; do
  if ! command -v "$command" >/dev/null 2>&1; then
    printf '缺少构建工具：%s\n' "$command" >&2
    exit 1
  fi
done
if [[ ! -f "$source_dir/app.py" ]]; then
  printf '找不到 app.py，请先准备完整源码。\n' >&2
  exit 1
fi

mkdir -p -- "$output_dir"
output_dir=$(cd -- "$output_dir" && pwd)
build_dir=$(mktemp -d -t netease-cloud-music-build.XXXXXXXX)
trap 'rm -rf -- "$build_dir"' EXIT
stage="$build_dir/package"
install -d "$stage/DEBIAN" "$stage/usr/bin" \
  "$stage/usr/share/netease-cloud-music/assets" \
  "$stage/usr/share/applications" \
  "$stage/usr/share/icons/hicolor/scalable/apps" \
  "$stage/usr/share/doc/$package_name"
install -m 0644 "$source_dir/packaging/control" "$stage/DEBIAN/control"
install -m 0755 "$source_dir/packaging/netease-cloud-music" "$stage/usr/bin/netease-cloud-music"
install -m 0644 "$source_dir/app.py" "$stage/usr/share/netease-cloud-music/app.py"
install -m 0644 "$source_dir/assets/"*.svg "$stage/usr/share/netease-cloud-music/assets/"
install -m 0644 "$source_dir/assets/netease-cloud-music.svg" "$stage/usr/share/icons/hicolor/scalable/apps/netease-cloud-music.svg"
install -m 0644 "$source_dir/packaging/netease-cloud-music.desktop" "$stage/usr/share/applications/netease-cloud-music.desktop"
install -m 0644 "$source_dir/README.md" "$stage/usr/share/doc/$package_name/README.zh-CN.md"
installed_size=$(du -sk -- "$stage/usr" | cut -f1)
printf 'Installed-Size: %s\n' "$installed_size" >> "$stage/DEBIAN/control"

deb_path="$output_dir/${package_name}_${version}_all.deb"
dpkg-deb -Zgzip --root-owner-group --build "$stage" "$deb_path"

archive_root="$build_dir/netease-cloud-music-$version"
install -d "$archive_root"
cp -R -- "$source_dir/app.py" "$source_dir/assets" "$source_dir/packaging" \
  "$source_dir/build-package.sh" "$source_dir/install.sh" "$source_dir/install-dependencies.sh" \
  "$source_dir/uninstall.sh" "$source_dir/README.md" "$source_dir/.gitignore" "$archive_root/"
install -d "$archive_root/tests"
install -m 0644 "$source_dir/tests/"*.py "$archive_root/tests/"
install -d "$archive_root/.github/workflows"
install -m 0644 "$source_dir/.github/workflows/compatibility.yml" "$archive_root/.github/workflows/compatibility.yml"
tar -C "$build_dir" --owner=0 --group=0 -czf \
  "$output_dir/netease-cloud-music-${version}-source.tar.gz" "netease-cloud-music-$version"
printf '已生成安装包：%s\n已生成源码包：%s\n' \
  "$deb_path" "$output_dir/netease-cloud-music-${version}-source.tar.gz"
