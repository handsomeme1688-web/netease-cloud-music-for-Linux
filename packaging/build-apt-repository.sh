#!/usr/bin/env bash
set -euo pipefail
umask 022

if [[ $# -ne 3 ]]; then
  printf '用法：%s <安装包.deb> <APT 输出目录> <签名密钥指纹>\n' "$0" >&2
  exit 2
fi

package=$(realpath -- "$1")
destination=$(realpath -m -- "$2")
fingerprint=${3^^}
if [[ ! "$fingerprint" =~ ^[0-9A-F]{40}$ || \
      $(dpkg-deb -f "$package" Package) != netease-cloud-music-webkit || \
      $(dpkg-deb -f "$package" Architecture) != all ]]; then
  printf '请提供网易云音乐安装包和完整的签名密钥指纹。\n' >&2
  exit 2
fi
version=$(dpkg-deb -f "$package" Version)
dpkg --validate-version "$version"
filename="netease-cloud-music-webkit_${version}_all.deb"

stage=$(mktemp -d -t music-apt.XXXXXXXX)
trap 'rm -rf -- "$stage"' EXIT
(
  cd -- "$stage"
  mkdir -p pool by-hash/SHA256
  install -m 0644 -- "$package" "pool/$filename"
  dpkg-scanpackages pool > Packages
  gzip -n -9c Packages > Packages.gz

  {
    printf 'Origin: NetEase Cloud Music for Linux\nLabel: NetEase Cloud Music for Linux\n'
    printf 'Suite: ./\nCodename: ./\nDate: %s\n' "$(LC_ALL=C date -u -R)"
    printf 'Acquire-By-Hash: yes\nDescription: NetEase Cloud Music packages for Debian and Ubuntu\nSHA256:\n'
    for index in Packages Packages.gz; do
      digest=$(sha256sum -- "$index")
      digest=${digest%% *}
      install -m 0644 -- "$index" "by-hash/SHA256/$digest"
      printf ' %s %s %s\n' "$digest" "$(wc -c < "$index")" "$index"
    done
  } > Release

  gpg --batch --armor --export "$fingerprint" > archive-key.asc
  gpg --batch --local-user "$fingerprint" --digest-algo SHA256 --output InRelease --clearsign Release
)
mkdir -p -- "$destination"
cp -R -- "$stage"/. "$destination/"
