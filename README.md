# 网易云音乐 · Linux 独立窗口版

将 <https://music.163.com/st/webplayer> 作为独立 Debian/Ubuntu 桌面应用运行。
使用 Python 3、GTK 3 和 WebKitGTK，优先加载 4.1 接口，旧系统可回退到 4.0 接口，不需要安装或借用 Chrome、Chromium、Electron。
它拥有独立窗口、应用菜单入口和独立的网页登录数据；仍需联网访问网易云音乐网页。
这是非官方网页封装客户端，界面、账号登录、曲库、会员权限及播放能力由原网站提供。

## 安装 .deb 包

从 [Releases 页面](https://github.com/handsomeme1688-web/netease-cloud-music-webkit/releases) 下载最新的 `.deb` 安装包。

在 Debian/Ubuntu 桌面打开终端，切换到安装包所在目录后运行：

```sh
sudo apt install ./netease-cloud-music-webkit_1.0.1_all.deb
```

APT 会根据本机发行版和架构解析安装包声明的全部依赖，并选择仓库可用的 WebKitGTK 接口。安装完成后，在应用菜单中搜索“网易云音乐”，或在终端执行：

```sh
netease-cloud-music
```

此包面向满足下列依赖的 Debian、Ubuntu 及其衍生发行版。
`all` 表示本应用使用 Python 源码，不包含绑定 CPU 架构的二进制；WebKitGTK 等系统依赖仍须支持你的系统架构。
`.deb` 显式使用 gzip 压缩，以便这些发行版中的旧版 dpkg 也能解包。
运行需要已有的 X11 或 Wayland 图形桌面、会话 D-Bus、可用的音频输出和互联网连接。

## 运行依赖

最低接口要求为 **Python 3.8、GTK 3.24、WebKitGTK 2.28**。其中 4.1 接口需要 WebKitGTK 2.36 或以上；4.0 接口需要 2.28 或以上。`4.1`、`4.0` 是 GI 接口版本，`2.xx` 是 WebKitGTK 引擎版本。程序使用 GTK 3，因此 `gir1.2-webkit-6.0` 不能直接替代这两个接口。

以下是本应用明确声明的运行依赖。Python 部分仅使用标准库和系统提供的 PyGObject：

| 系统软件包 | 作用 |
| --- | --- |
| `python3`（≥ 3.8） | Python 解释器及标准库 |
| `python3-gi`（≥ 3.36） | Python 调用 GTK、Gio 和 WebKitGTK 的绑定 |
| `gir1.2-gtk-3.0`（≥ 3.24） | GTK 3、GDK 等图形接口 |
| `gir1.2-webkit2-4.1`（≥ 2.36）或 `gir1.2-webkit2-4.0`（≥ 2.28） | 网页渲染接口；优先使用 4.1 |
| `ca-certificates` | 验证 HTTPS 网站证书 |
| `librsvg2-common` | 为 GdkPixbuf 提供 SVG 图标加载支持 |
| `gstreamer1.0-plugins-base` | 基础音视频处理组件 |
| `gstreamer1.0-plugins-good` | 常用音视频格式与流媒体组件 |
| `gstreamer1.0-libav` | FFmpeg/libav 解码插件 |
| `gstreamer1.0-plugins-good`（≥ 1.18）或 `gstreamer1.0-pulseaudio` | 提供 PulseAudio 输出，连接已有 PulseAudio 或 PipeWire 的 PulseAudio 兼容服务；较新 good 包已合并此插件 |
| `gstreamer1.0-alsa` | ALSA 音频输出插件 |

安装音频插件沿用系统现有音频服务，不会要求安装整个桌面，也不需要切换音频服务。

### 由 APT 自动解析的系统库

上述软件包还会按发行版和架构带入各自依赖，包括：

- GLib、GObject、Gio、GObject Introspection，以及 GTK/GDK。
- Pango、Cairo、GdkPixbuf、librsvg、字体渲染与图像解码库。
- WebKitGTK 引擎和配套 JavaScriptCore。4.1 接口使用 libsoup 3，4.0 接口使用 libsoup 2.4，以及相应的 TLS/网络组件。
- GStreamer 核心、音视频解码库、音频输出客户端库。
- SQLite、系统 C/C++ 运行库、X11/Wayland 和图形渲染组件；需要时还有 WebKitGTK 沙箱组件。

这些是传递依赖，具体包名、版本和 `.so` 文件会随发行版变化，应由 APT 根据包元数据完整解析，无需逐个手工安装或从其他发行版复制系统库。依赖关系可参考 Debian 官方的 [WebKitGTK 4.1 接口包](https://packages.debian.org/bookworm/gir1.2-webkit2-4.1)、[4.0 接口包](https://packages.debian.org/bookworm/gir1.2-webkit2-4.0)、[引擎运行库](https://packages.debian.org/bookworm/libwebkit2gtk-4.1-0)和 [SVG 加载模块](https://packages.debian.org/bookworm/librsvg2-common)。

### 推荐与可选组件

安装包推荐 `fonts-noto-cjk` 或 `fonts-wqy-microhei`，用于完整显示中文；并推荐 `dbus-user-session` 或 `dbus-x11`，为桌面应用提供会话 D-Bus。已有完整桌面的系统通常已经具备会话服务。Noto 字体支持的文字范围见 [Debian 官方字体说明](https://packages.debian.org/bookworm/fonts-noto-cjk)。

按需安装中文字体：

```sh
sudo apt install fonts-noto-cjk
```

如特定音视频格式缺少插件，可按需补充 [GStreamer bad 插件集](https://packages.debian.org/bookworm/gstreamer1.0-plugins-bad)和 [ugly 插件集](https://packages.debian.org/bookworm/gstreamer1.0-plugins-ugly)：

```sh
sudo apt install gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly
```

额外插件不能改变网站的会员、版权或浏览器能力限制。`desktop-file-utils` 和 `gtk-update-icon-cache` 仅用于安装后刷新桌面入口及图标缓存，安装脚本会在这些工具存在时调用。

## 发行版范围与包可用性

下表根据官方软件包索引、发行说明和历史归档核对，列出依赖可用的安装路线。**软件包可用、达到最低 API 门槛，不等于所有网页功能或所有硬件都已实机验证。**目前实际图形运行验证环境为 Ubuntu 26.04；其他列出的版本仍需结合本机显示驱动、桌面、音频、网络和网站响应验证。

| 发行版 | 默认 Python 3 | GTK 3 | 官方源中的 WebKitGTK 接口与安装路线 |
| --- | --- | --- | --- |
| Debian 11 Bullseye | [3.9](https://packages.debian.org/bullseye/python3) | [3.24](https://packages.debian.org/bullseye/gir1.2-gtk-3.0) | 使用 [4.0](https://packages.debian.org/bullseye/gir1.2-webkit2-4.0)；需要可用的历史仓库，见下文 |
| Debian 12 Bookworm | [3.11](https://packages.debian.org/bookworm/python3) | [3.24](https://packages.debian.org/bookworm/gir1.2-gtk-3.0) | 优先 [4.1](https://packages.debian.org/bookworm/gir1.2-webkit2-4.1)，也提供 [4.0](https://packages.debian.org/bookworm/gir1.2-webkit2-4.0) |
| Debian 13 Trixie | [3.13](https://packages.debian.org/trixie/python3) | [3.24](https://packages.debian.org/trixie/gir1.2-gtk-3.0) | 使用 [4.1](https://packages.debian.org/trixie/gir1.2-webkit2-4.1) |
| Ubuntu 20.04 LTS Focal | [3.8](https://ubuntu.com/developers/docs/reference/availability/python/) | [3.24](https://lists.ubuntu.com/archives/focal-changes/2024-July/048677.html) | 使用 4.0；见官方 [Focal 软件包记录](https://lists.ubuntu.com/archives/ubuntu-studio-devel/2020-July/009373.html)与 [WebKitGTK 更新记录](https://lists.ubuntu.com/archives/focal-changes/2022-November/037110.html) |
| Ubuntu 22.04 LTS Jammy | [3.10](https://ubuntu.com/developers/docs/reference/availability/python/) | [3.24](https://packages.ubuntu.com/jammy/gir1.2-gtk-3.0) | 优先 [4.1](https://packages.ubuntu.com/jammy/gir1.2-webkit2-4.1)（universe），也提供 [4.0](https://packages.ubuntu.com/jammy/gir1.2-webkit2-4.0) |
| Ubuntu 24.04 LTS Noble | [3.12](https://ubuntu.com/developers/docs/reference/availability/python/) | [3.24](https://packages.ubuntu.com/noble/gir1.2-gtk-3.0) | 使用 [4.1](https://packages.ubuntu.com/noble/gir1.2-webkit2-4.1) |
| Ubuntu 26.04 LTS Resolute | [3.14](https://packages.ubuntu.com/en/resolute/python3) | [3.24](https://packages.ubuntu.com/source/resolute/gtk%2B3.0) | 使用 [4.1](https://packages.ubuntu.com/resolute/gir1.2-webkit2-4.1) |

表中的 Python/GTK 版本为主、次版本，补丁版本会随更新变化。旧发行版需保持其官方更新源可用；Ubuntu 部分依赖位于 universe，应先启用该组件并刷新软件包索引。其他 Debian 系发行版可按其基础版本和自身软件源选择 4.1 或 4.0，不能仅凭“基于 Debian”保证可运行。

Debian 11 已于 **2026-08-31 结束 LTS**，详见 [Debian 官方公告](https://www.debian.org/News/2026/20260831)。其安全更新索引引用的部分包已不在官方 security pool 中，可能出现下载 404，见 [Debian 问题记录](https://bugs.debian.org/1147150)。自动检查仅在临时容器中使用官方 `20260831T235959Z` 安全更新快照，保留签名验证，并按 [Debian Snapshot 官方文档](https://snapshot.debian.org/)只对该快照关闭有效期检查。用户安装脚本不会自动修改软件源；使用 Debian 11 前需确认自己的仓库能够提供完整依赖，上表中的历史包记录不代表默认源仍可完成安装。

可先检查本机仓库提供的候选版本：

```sh
apt-cache policy python3 gir1.2-gtk-3.0 gir1.2-webkit2-4.1 gir1.2-webkit2-4.0
```

## 仅安装到当前用户

在完整源码目录中，推荐先运行依赖安装脚本。脚本刷新 APT 软件包索引，优先选择仓库可用的 4.1 接口，不可用时选择 4.0：

```sh
bash install-dependencies.sh
```

也可以手工安装。软件源提供 4.1 时运行：

```sh
sudo apt update
sudo apt install python3 python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 \
  ca-certificates librsvg2-common gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good gstreamer1.0-libav \
  gstreamer1.0-pulseaudio gstreamer1.0-alsa
```

旧发行版只有 4.0 时运行：

```sh
sudo apt update
sudo apt install python3 python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.0 \
  ca-certificates librsvg2-common gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good gstreamer1.0-libav \
  gstreamer1.0-pulseaudio gstreamer1.0-alsa
```

两条命令选择一条即可。然后在源码目录运行用户安装脚本，无需 sudo：

```sh
bash install.sh
```

默认程序目录是 `~/.local/share/netease-cloud-music/app`，启动器为 `~/.local/bin/netease-cloud-music`。
应用菜单入口保存在 `~/.local/share/applications`，不依赖 `~/.local/bin` 是否已加入 `PATH`。
安装和卸载支持绝对路径的 `XDG_DATA_HOME`、`XDG_CACHE_HOME`、`XDG_CONFIG_HOME`，并允许用 `XDG_BIN_HOME` 改变启动器目录。
含空格的路径会正确引用。卸载时请保持与安装时相同的这些环境变量。

依赖脚本需要系统提供 `apt-get`、`apt-cache`、`dpkg` 和 `awk`，普通用户运行时还需要 `sudo`；这些通常由 Debian/Ubuntu 基础系统提供。

## 登录与播放

首次运行后直接在官方网页内登录；登录数据与浏览器分开保存，重启后继续使用。
登录 Cookie 默认保存为 `~/.local/share/netease-cloud-music/cookies.sqlite`，其他网页数据位于同目录的 `webkit/`。
缓存目录为 `~/.cache/netease-cloud-music/webkit/`，窗口配置为 `~/.config/netease-cloud-music/window.json`。相应 XDG 环境变量可改变基础目录。
本程序不收集或转发账号密码，也不绕过原网站的会员、版权、区域或播放限制。
如网站不支持当前 WebKitGTK 版本、出现网络限制或要求额外验证，可能影响某些功能。
网页目前只接受特定浏览器标识，因此应用发送 Firefox 兼容标识以通过该检查；实际运行引擎始终是 WebKitGTK，也无需安装 Firefox。
关闭窗口会停止播放。支持 Ctrl+R 刷新、Alt+方向键前进/后退、Ctrl++ / Ctrl+- 缩放和 Ctrl+Q 退出。
已移除顶部工具栏与标题栏，网页直接从窗口顶边显示。最小化、最大化／还原、关闭三个原生按钮集成在内容区右上角，网易云顶栏右侧留出空间，避免遮挡账号和皮肤等入口。F10 不再恢复工具栏。Alt+Home 返回播放器首页，Alt+F4 关闭窗口，Ubuntu 默认可按住 Super（Windows 徽标键）拖动窗口。弹窗同样使用内部窗口按钮；视频全屏时暂时隐藏按钮，退出全屏后恢复。

## 窗口显示

右上角窗口按钮采用透明底和灰蓝细线图标，与网页顶栏保持接近的视觉风格；只有悬停时显示轻微反馈，关闭按钮悬停时变为网易云红色。

Wayland 桌面下，应用优先使用原生 Wayland，连接不可用时自动回退到 X11。此设置仅作用于本应用，不会修改系统的显示器、缩放或动画设置。窗口切换焦点、最小化和恢复时不会重建最大化按钮。

如需排查旧驱动兼容性，先退出应用，再用 `NETEASE_MUSIC_BACKEND=x11 netease-cloud-music` 临时选择 X11；也可用 `NETEASE_MUSIC_BACKEND=wayland` 强制原生 Wayland。已经运行的实例须退出后才会使用新的显示后端。

## Ubuntu 22.04 与启动排查

最低依赖见“运行依赖”一节。v1.0.1 补充了旧版 JavaScript 接口和网页响应处理兼容，避免在较旧的 WebKitGTK 中调用不存在的方法。发行版名称不能直接判断 WebKitGTK 版本：同一系统可能已通过官方更新获得较新的引擎。

v1.0.1 同时修正了首页被当成下载文件的处理：对返回 HTML 的播放器首页明确执行页面显示；对非网页内容、空响应或 HTTP 错误显示具体状态、WebKit 内容类型和原始响应头，不再弹出保存 `webplayer` 的对话框。正常重定向和其他地址的下载仍由各自流程处理。

如果窗口出现但网页全白，先完全退出应用，再在终端检查运行版本：

```sh
netease-cloud-music --check
```

若怀疑是显卡渲染兼容问题，可临时尝试：

```sh
WEBKIT_DISABLE_DMABUF_RENDERER=1 netease-cloud-music
```

这是 WebKitGTK 提供的渲染排查选项，仅影响此次启动；不同版本和显卡的效果可能不同。应用采用单实例运行，已有窗口必须先关闭，重新运行命令才能让新的环境设置生效。若仍然白屏，请提供 `--check` 输出及完全退出后重新启动时的终端错误。

## 卸载

若使用 .deb 安装：

```sh
sudo apt remove netease-cloud-music-webkit
```

若使用当前用户安装脚本安装，在原源码目录运行：

```sh
bash uninstall.sh
```

也可运行安装目录中的 `uninstall.sh`。默认卸载保留登录数据、缓存与窗口配置。
要同时删除当前用户安装的登录数据、缓存与窗口配置，请先退出应用，然后运行：

```sh
bash uninstall.sh --purge
```

## 从源码构建

构建工具为 `bash`、`coreutils`、`dpkg`（提供 `dpkg-deb`）、`tar`、`gzip` 和 `python3`。其中 `coreutils` 提供复制、创建目录、计算体积和临时目录等命令；构建脚本通过 `dpkg-deb -Zgzip` 显式使用 gzip 压缩 `.deb`，源码包也使用 gzip。安装构建工具：

```sh
sudo apt install bash coreutils dpkg tar gzip python3
```

工具就绪后，构建本身无需 root、网络或 GUI 运行依赖：

```sh
bash build-package.sh ./dist
```

生成 `netease-cloud-music-webkit_1.0.1_all.deb` 和 `netease-cloud-music-1.0.1-source.tar.gz`。
未提供输出目录时，使用源码目录下的 `dist`。
在已安装运行依赖的环境中，可运行兼容性回归测试（无需打开窗口）：

```sh
python3 -m unittest discover -s tests -v
```

仓库的 [自动兼容性检查](https://github.com/handsomeme1688-web/netease-cloud-music-webkit/actions/workflows/compatibility.yml)先在 Ubuntu 26.04 构建一个 `.deb`，再让表中的七种系统安装同一产物，检查依赖、运行库、图标、音频插件及回归测试，最新结果见链接。容器检查不包含真实显卡、桌面会话、账号登录或在线音乐播放；实际图形运行验证仍仅限 Ubuntu 26.04。

图标的原始品牌图像来自[网易云音乐官网提供的高清标识](https://p3.music.126.net/9z9CeujRSPOPm7Rq2DFw_g==/6674035581283071.jpg)，在 SVG 中采用参考 macOS 的连续圆角裁剪、透明留白与轻微阴影，以适配桌面图标的显示。本软件仍是非官方网页封装。
