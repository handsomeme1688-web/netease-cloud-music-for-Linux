# 网易云音乐 · Linux 独立窗口版

网易云音乐的非官方 Linux 客户端，基于 Python、GTK 3 和 WebKitGTK，无需 Chrome、Chromium 或 Electron。
支持扫码登录、音质选择、高分屏、无边框窗口和系统媒体控制。

**[下载安装包](https://github.com/handsomeme1688-web/netease-cloud-music-for-Linux/releases/latest) · [反馈问题](https://github.com/handsomeme1688-web/netease-cloud-music-for-Linux/issues)**

<img width="1299" height="890" alt="网易云音乐播放界面" src="https://github.com/user-attachments/assets/c6ae1119-c897-412e-8533-157fdf71172c" />

## 安装

适用于 Debian / Ubuntu 桌面，需要 X11 或 Wayland、会话 D-Bus、音频输出和网络。应用始终使用直连。

### 使用 APT 软件源

配置一次后，网易云音乐可随系统一起更新。已经通过 `.deb` 安装的用户也可以添加此源，继续使用原来的登录、设置和缓存。

```sh
(
  set -e
  repo='https://handsomeme1688-web.github.io/netease-cloud-music-for-Linux/apt/'
  fingerprint='D85075468B056509564B78D9F85270F94961FB3B'
  key=$(mktemp)
  trap 'rm -f "$key"' EXIT
  curl -fsSL "${repo}archive-key.asc" -o "$key"
  sudo install -D -m 0644 "$key" /etc/apt/keyrings/netease-cloud-music.asc
  printf 'deb [signed-by=/etc/apt/keyrings/netease-cloud-music.asc,%s] %s ./\n' "$fingerprint" "$repo" |
    sudo tee /etc/apt/sources.list.d/netease-cloud-music.list >/dev/null
  sudo apt update
  sudo apt install netease-cloud-music-webkit
)
```

以后运行 `sudo apt update && sudo apt upgrade` 即可升级。

### 下载安装包

下载 `.deb` 后，在安装包所在目录运行：

```sh
sudo apt install ./netease-cloud-music-webkit_1.3.1_all.deb
```

APT 自动安装依赖。安装后在应用菜单中打开“网易云音乐”，点击右上角“登录”扫码。账号、曲库和会员权限由官方网页提供。

### 从源码安装

在源码目录运行：

```sh
bash install-dependencies.sh
bash install.sh
```

### 运行依赖

最低要求：Python 3.8、GTK 3.24、WebKitGTK 2.28；优先使用 WebKitGTK 4.1 接口，旧系统使用 4.0。

<details>
<summary>完整依赖列表</summary>

| 用途 | 软件包 |
| --- | --- |
| Python | `python3` ≥ 3.8、`python3-gi` ≥ 3.36、`python3-gi-cairo` |
| GTK | `gir1.2-gtk-3.0` ≥ 3.24 |
| WebKitGTK | `gir1.2-webkit2-4.1` ≥ 2.36 或 `gir1.2-webkit2-4.0` ≥ 2.28 |
| HTTP | `gir1.2-soup-3.0`（4.1）或 `gir1.2-soup-2.4`（4.0），随 WebKitGTK 安装 |
| HTTPS | `ca-certificates`、`openssl` |
| 图标 | `librsvg2-common` |
| 音频解码 | `gir1.2-gstreamer-1.0`、`gstreamer1.0-plugins-base`、`gstreamer1.0-plugins-good`、`gstreamer1.0-libav` |
| 音频输出 | `gstreamer1.0-alsa`，以及 `gstreamer1.0-plugins-good` ≥ 1.18 或 `gstreamer1.0-pulseaudio` |
| 中文字体（推荐） | `fonts-noto-cjk` 或 `fonts-wqy-microhei` |
| 会话 D-Bus（推荐） | `dbus-user-session` 或 `dbus-x11` |

其余系统库由 APT 解析安装。Ubuntu 部分依赖位于 `universe`；Debian 11 需使用可用的历史软件源。

</details>

[自动安装与回归检查](https://github.com/handsomeme1688-web/netease-cloud-music-for-Linux/actions/workflows/compatibility.yml)覆盖 Debian 11 / 12 / 13 和 Ubuntu 20.04 / 22.04 / 24.04 / 26.04，采用容器测试；桌面实测环境为 Ubuntu 26.04。

## 使用

设置 → 播放、底部播放栏和歌曲详情页共用默认音质。改动后，当前歌曲按可用档位继续播放，播放栏显示实际音质。菜单按账号权限提供标准、极高、无损、Hi-Res、高清臻音、超清母带等档位。

音乐先缓冲再起播。当前歌曲下载完后，网络条件允许时按播放顺序预载最多三首。额外预载逐首进行，优先为正在播放的歌曲让出带宽。已完整验证并缓存的歌曲会保留在本地，重播和重开应用时可复用。
设置 → 播放可查看和更改音乐缓存目录。选择文件夹后，新缓存写入其中的 `netease-cloud-music-audio` 子目录，旧缓存留在原处。

音乐缓存目录下方可设置下载目录和音质。支持极高（MP3）、无损（FLAC）、超清母带和沉浸环绕声。单曲可用收藏左侧的下载按钮或右键菜单下载，歌单页可批量下载。在播放栏音质左边查看进度或下载当前歌曲。歌曲行的对勾表示当前下载音质已有文件。超清母带和沉浸环绕声仅在网易云返回所选档位时保存。官方提供的加密 NCM 文件原样保存，缺少加密文件的受保护授权会跳过。

设置 → 播放 → 歌曲过渡可选择淡入淡出或混音过渡，时长为 1～12 秒。混音过渡会同时播放上一首的尾段和下一首的开头。缓冲不足时按正常音量切歌。

点击播放栏音质旁的「词」按钮，或按 `Ctrl+D`，开关桌面歌词。当前歌词单行显示，有逐字时间轴的歌曲会逐字渐亮。解锁时，悬停可播放或暂停、切歌、拖动窗口和调整样式。锁定后进入无边框模式，悬停时只显示「解锁」。

臻音全景声需要播放引擎支持 AV3A 解码；缺少支持时，菜单会注明并灰显该项。

拖动窗口顶部空白处或搜索框右侧的空白区可移动窗口，双击可最大化或还原。拖动边缘或四角调整大小。点击封面或歌曲名可展开歌曲详情。关闭窗口会停止播放。
应用以普通窗口打开，默认 1080×720，常规最小为 800×540（逻辑像素）。小屏幕会按桌面的可用空间调小窗口尺寸。

界面随窗口宽度和桌面缩放调整。窄窗中窗口按钮单独成行，播放栏分行排列。空间不足时会暂时调低网页缩放，放大窗口后恢复原设定。

| 快捷键 | 操作 |
| --- | --- |
| `Ctrl+R` | 刷新页面 |
| `Ctrl+Shift+R` | 恢复播放器，保留登录 |
| `Ctrl+D` | 显示或关闭桌面歌词 |
| `Ctrl++` / `Ctrl+-` | 缩放界面 |
| `Alt+Home` | 返回播放器首页 |
| `Ctrl+Q` | 退出 |

## 常见问题

**无法启动或白屏：** 完全退出应用后，查看运行环境：

```sh
netease-cloud-music --check
```

显卡渲染异常时，可尝试：

```sh
WEBKIT_DISABLE_DMABUF_RENDERER=1 netease-cloud-music
```

提交 Issue 时请附上发行版、桌面环境、软件版本、`--check` 输出和复现步骤。

## 卸载

```sh
sudo apt remove netease-cloud-music-webkit
```

源码安装使用 `bash uninstall.sh`。默认保留用户数据；加 `--purge` 可一并清理。

## 开发

构建工具：`bash`、`coreutils`、`dpkg`、`tar`、`gzip`、`python3`。生成的安装包和源码包位于 `dist/`。

```sh
bash build-package.sh ./dist
```

发布新版时，在签名机器上运行 `bash packaging/build-apt-repository.sh <安装包.deb> <gh-pages检出目录>/apt <签名密钥指纹>`，再提交并推送 `gh-pages`。生成脚本依赖 `dpkg-dev` 和 GnuPG，用 `GNUPGHOME` 指定签名密钥目录。

安装运行依赖和 `nodejs` 后执行测试：

```sh
python3 -m unittest discover -s tests -v
```

图标素材来自[网易云音乐官方标识](https://p3.music.126.net/9z9CeujRSPOPm7Rq2DFw_g==/6674035581283071.jpg)。
