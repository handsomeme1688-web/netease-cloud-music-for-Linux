# 网易云音乐 · Linux 独立窗口版

网易云音乐的非官方 Linux 客户端，基于 Python、GTK 3 和 WebKitGTK，无需 Chrome、Chromium 或 Electron。
支持扫码登录、音质选择、高分屏、无边框窗口和系统媒体控制。

**[下载安装包](https://github.com/handsomeme1688-web/netease-cloud-music-for-Linux/releases/latest) · [反馈问题](https://github.com/handsomeme1688-web/netease-cloud-music-for-Linux/issues)**

<img src="https://github.com/user-attachments/assets/598fc2d5-7a3a-4007-83ce-21f54234a8db" alt="网易云音乐播放界面" width="960" />

## 安装

适用于 Debian / Ubuntu 桌面，需要 X11 或 Wayland、会话 D-Bus、音频输出和网络。

下载 `.deb` 后，在安装包所在目录运行：

```sh
sudo apt install ./netease-cloud-music-webkit_1.0.11_all.deb
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
| Python | `python3` ≥ 3.8、`python3-gi` ≥ 3.36 |
| GTK | `gir1.2-gtk-3.0` ≥ 3.24 |
| WebKitGTK | `gir1.2-webkit2-4.1` ≥ 2.36 或 `gir1.2-webkit2-4.0` ≥ 2.28 |
| HTTP | `gir1.2-soup-3.0`（4.1）或 `gir1.2-soup-2.4`（4.0），随 WebKitGTK 安装 |
| HTTPS | `ca-certificates`、`openssl` |
| 图标 | `librsvg2-common` |
| 音频解码 | `gstreamer1.0-plugins-base`、`gstreamer1.0-plugins-good`、`gstreamer1.0-libav` |
| 音频输出 | `gstreamer1.0-alsa`，以及 `gstreamer1.0-plugins-good` ≥ 1.18 或 `gstreamer1.0-pulseaudio` |
| 中文字体（推荐） | `fonts-noto-cjk` 或 `fonts-wqy-microhei` |
| 会话 D-Bus（推荐） | `dbus-user-session` 或 `dbus-x11` |

其余系统库由 APT 解析安装。Ubuntu 部分依赖位于 `universe`；Debian 11 需使用可用的历史软件源。

</details>

[自动安装与回归检查](https://github.com/handsomeme1688-web/netease-cloud-music-for-Linux/actions/workflows/compatibility.yml)覆盖 Debian 11 / 12 / 13 和 Ubuntu 20.04 / 22.04 / 24.04 / 26.04，采用容器测试；桌面实测环境为 Ubuntu 26.04。

## 使用

点击底部音质按钮选择标准、极高、无损、Hi-Res、高清臻音、超清母带、沉浸环绕声或臻音全景声。菜单按账号与歌曲权限显示可选项，保存音质偏好，并显示实际播放档位。

歌曲完整加载后播放，播放期间预载队列中的下一首。首次加载时，底部音质按钮显示下载进度。

臻音全景声需要播放引擎支持 AV3A 解码；缺少支持时，菜单会注明并灰显该项。

拖动窗口顶部空白处移动窗口，双击可最大化或还原；拖动边缘或四角调整大小。关闭窗口会停止播放。

| 快捷键 | 操作 |
| --- | --- |
| `Ctrl+R` | 刷新页面 |
| `Ctrl+Shift+R` | 恢复播放器，保留登录 |
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

**HTTP 400 或代理异常：** 完全退出应用后，切换为直连，再重新打开：

```sh
netease-cloud-music --set-proxy-mode direct
```

恢复系统代理使用 `netease-cloud-music --set-proxy-mode system`。

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

安装运行依赖和 `nodejs` 后执行测试：

```sh
python3 -m unittest discover -s tests -v
```

图标素材来自[网易云音乐官方标识](https://p3.music.126.net/9z9CeujRSPOPm7Rq2DFw_g==/6674035581283071.jpg)。
