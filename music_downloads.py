"""Save files granted by the official song download service."""

from contextlib import suppress
import hashlib
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import time
from typing import NamedTuple
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from gi.repository import Gio, GLib

from audio_buffer import CHUNK_BYTES, MAX_DOWNLOAD_BYTES, audio_uri
from quality_service import encode_request


ORIGIN = "https://music.163.com"
DOWNLOAD_PATH = "/api/song/enhance/download/url/v1"
DESKTOP_DOWNLOAD = "https://interfacepc.music.163.com/eapi/song/enhance/download/url/v1"
DESKTOP_VERSION = "3.1.17.204416"
DESKTOP_USER_AGENT = f"NeteaseMusicDesktop/{DESKTOP_VERSION}"
SESSION_COOKIES = {"MUSIC_U", "MUSIC_A", "__csrf", "NMTID"}


class DownloadOption(NamedTuple):
    level: str
    extension: str
    label: str
    exact: bool = False


FORMATS = {
    "mp3": DownloadOption("exhigh", "mp3", "极高（MP3）"),
    "flac": DownloadOption("lossless", "flac", "无损（FLAC）"),
    "jymaster": DownloadOption("jymaster", "flac", "超清母带", exact=True),
    "sky": DownloadOption("sky", "flac", "沉浸环绕声", exact=True),
}


class DownloadError(Exception):
    pass


class DownloadUnavailable(DownloadError):
    pass


class DownloadCancelled(DownloadError):
    pass


class LoginRequired(DownloadError):
    pass


class DownloadRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, handle, code, message, headers, new_url):
        # Never send the account session to a redirect or follow an off-CDN link.
        target = audio_uri(new_url) if audio_uri(request.full_url) else None
        if not target:
            return None
        return super().redirect_request(request, handle, code, message, headers, target)


def resource_id(value):
    text = str(value)
    if re.fullmatch(r"[1-9][0-9]{0,15}", text):
        identifier = int(text)
        if identifier < 2**53:
            return identifier
    return None


def file_label(value, fallback):
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]', "_", str(value or "")).strip(" .")
    return text.encode("utf-8", "replace")[:150].decode("utf-8", "ignore") or str(fallback)


def load_preferences(path, fallback):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        directory = Path(value["directory"])
        if directory.is_absolute() and "\0" not in str(directory):
            format_name = value.get("format")
            return directory, format_name if format_name in FORMATS else "mp3"
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return fallback, "mp3"


def download_suffixes(format_name):
    option = FORMATS[format_name]
    label = f" [{option.label}]" if option.exact else ""
    return f"{label}.{option.extension}", f"{label or f' [{option.extension.upper()}]'}.ncm"


def downloaded_songs(directory, format_name):
    plain, encrypted = map(re.escape, download_suffixes(format_name))
    filename = re.compile(r" \[([1-9]\d{0,15})\](?:" + plain + "|" + encrypted + r")$")
    playlist = re.compile(r" \[[1-9]\d{0,15}\]$")
    found = set()
    folders = [directory]
    for folder in folders:
        with suppress(OSError), os.scandir(folder) as entries:
            for entry in entries:
                with suppress(OSError):
                    if folder == directory and playlist.search(entry.name) and entry.is_dir(follow_symlinks=False):
                        folders.append(entry.path)
                    match = filename.search(entry.name)
                    if match and entry.is_file(follow_symlinks=False) and entry.stat(follow_symlinks=False).st_size > 0:
                        identifier = resource_id(match[1])
                        if identifier:
                            found.add(str(identifier))
    return found


def downloadable_audio(response, song, format_name):
    option = FORMATS[format_name]
    if not isinstance(response, dict) or response.get("code") != 200:
        raise DownloadUnavailable("官方未授予此歌曲下载权限")
    grant = response.get("data")
    if not isinstance(grant, dict) or grant.get("code") != 200 or resource_id(grant.get("id")) != song:
        raise DownloadUnavailable("官方未授予此歌曲下载权限")

    if grant.get("freeTrialInfo"):
        raise DownloadUnavailable("网易云只返回了试听片段")
    flags, purchased = grant.get("flag"), grant.get("payed", 0)
    if type(flags) is not int:
        raise DownloadError("网易云返回的下载授权信息不完整")
    if option.exact and grant.get("level") != option.level:
        raise DownloadUnavailable(f"网易云未授予此歌曲的「{option.label}」下载")
    url = audio_uri(grant.get("url"))
    if not url:
        raise DownloadUnavailable(f"官方未提供「{option.label}」下载文件")
    encrypted = (grant.get("encryptFile") or grant.get("type") == "ncm" or
                 urlsplit(url).path.lower().endswith(".ncm"))
    if not encrypted:
        protected = flags & 32 or (flags & 4 and (type(purchased) is not int or not purchased & 7))
        if protected:
            raise DownloadUnavailable("网易云要求受保护的离线文件，但未提供可保存的加密版本")
        if grant.get("type") != option.extension:
            raise DownloadUnavailable(f"官方未提供「{option.label}」下载文件")
    size = grant.get("size")
    if type(size) is not int or not 0 < size <= MAX_DOWNLOAD_BYTES:
        raise DownloadError("官方文件大小无效")
    return url, size, grant.get("md5"), "ncm" if encrypted else option.extension


class MusicDownloads:
    def __init__(self, cookies, cancelled):
        self.csrf = cookies.get("__csrf", "")
        self.session = {
            key: value for key, value in cookies.items()
            if key in SESSION_COOKIES and re.fullmatch(r"[^\x00-\x20;\x7f]*", value)
        }
        self.cookie = "; ".join(f"{key}={value}" for key, value in self.session.items())
        self.device = secrets.token_hex(16)
        self.cancelled = cancelled
        self.opener = build_opener(ProxyHandler({}), DownloadRedirects())

    def check_cancelled(self):
        if self.cancelled.is_set():
            raise DownloadCancelled()

    def api(self, path, params):
        self.check_cancelled()
        form = urlencode(dict(params, csrf_token=self.csrf)).encode()
        request = Request(ORIGIN + path, data=form,
                          headers={"Referer": ORIGIN + "/st/webplayer", "Origin": ORIGIN,
                                   "Cookie": self.cookie, "Accept": "application/json"})
        return self.read_response(request)

    def read_response(self, request):
        with self.opener.open(request, timeout=15) as response:
            data = response.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            raise DownloadError("官网响应过大")
        value = json.loads(data)
        if not isinstance(value, dict):
            raise DownloadError("官网返回了无法识别的数据")
        if value.get("code") == 301:
            raise LoginRequired("请登录网易云音乐后下载")
        return value

    def download_grant(self, song, option):
        if not option.exact:
            return self.api(DOWNLOAD_PATH, {"id": song, "level": option.level, "encodeType": option.extension})
        self.check_cancelled()
        now = time.time()
        header = {"os": "pc", "osver": "Linux", "appver": DESKTOP_VERSION, "versioncode": "140",
                  "deviceId": self.device, "channel": "netease", "resolution": "1920x1080",
                  "buildver": str(int(now)), "requestId": f"{int(now * 1000)}_0000", **self.session}
        params = {"id": song, "level": option.level, "immerseType": "c51", "e_r": False, "header": header}
        try:
            body = encode_request(params, DOWNLOAD_PATH)
        except (OSError, subprocess.SubprocessError) as error:
            raise DownloadError("无法生成网易云桌面下载请求") from error
        request = Request(DESKTOP_DOWNLOAD, data=body,
                          headers={"Referer": ORIGIN + "/st/webplayer", "Accept": "application/json",
                                   "Content-Type": "application/x-www-form-urlencoded",
                                   "User-Agent": DESKTOP_USER_AGENT,
                                   "Cookie": urlencode(header).replace("&", "; ")})
        return self.read_response(request)

    def playlist(self, identifier):
        response = self.api("/api/v6/playlist/detail", {"id": identifier, "n": 0, "s": 0})
        playlist = response.get("playlist")
        if response.get("code") != 200 or not isinstance(playlist, dict):
            raise DownloadError("无法读取此歌单")
        entries = playlist.get("trackIds")
        if not isinstance(entries, list):
            raise DownloadError("官网未返回完整歌单")
        ids = [resource_id(entry.get("id")) if isinstance(entry, dict) else None for entry in entries]
        ids = list(dict.fromkeys(value for value in ids if value is not None))
        count = playlist.get("trackCount")
        if type(count) is int and count > len(entries):
            raise DownloadError("官网未返回完整歌单")
        return file_label(playlist.get("name"), identifier), ids

    def titles(self, songs):
        response = self.api("/api/v3/song/detail", {"c": json.dumps([{"id": song} for song in songs])})
        titles = {}
        for track in response.get("songs") or []:
            if not isinstance(track, dict) or not resource_id(track.get("id")):
                continue
            artists = [item.get("name") for item in track.get("ar") or []
                       if isinstance(item, dict) and isinstance(item.get("name"), str)]
            parts = [track.get("name"), "、".join(artists)]
            titles[int(track["id"])] = " - ".join(part for part in parts if isinstance(part, str) and part)
        return titles

    def download(self, directory, song, title, format_name, progress=None):
        option = FORMATS[format_name]
        stem = f"{file_label(title, song)} [{song}]"
        plain_suffix, encrypted_suffix = download_suffixes(format_name)
        plain = directory / (stem + plain_suffix)
        encrypted = directory / (stem + encrypted_suffix)
        if any(path.exists() or path.is_symlink() for path in (plain, encrypted)):
            return None
        grant = self.download_grant(song, option)
        url, size, expected_md5, extension = downloadable_audio(grant, song, format_name)
        target = encrypted if extension == "ncm" else plain
        temporary = None
        try:
            # Write into a private temporary file on the destination filesystem.
            with tempfile.NamedTemporaryFile(dir=directory, prefix=".netease-", suffix=".part",
                                             delete=False) as stream:
                temporary = Path(stream.name)
                self.copy_audio(url, size, expected_md5, extension, stream, progress)
            self.check_cancelled()
            Gio.File.new_for_path(str(temporary)).move(
                Gio.File.new_for_path(str(target)), Gio.FileCopyFlags.NONE, None, None)
            return target
        finally:
            if temporary is not None:
                with suppress(FileNotFoundError):
                    temporary.unlink()

    def copy_audio(self, url, size, expected_md5, extension, stream, progress=None):
        total, digest = 0, hashlib.md5()
        next_update = 0
        request = Request(url, headers={"Referer": ORIGIN + "/", "User-Agent": DESKTOP_USER_AGENT,
                                        "Accept-Encoding": "identity"})
        with self.opener.open(request, timeout=20) as response:
            if response.status != 200:
                raise DownloadError("CDN 返回了不完整的文件")
            while True:
                self.check_cancelled()
                chunk = response.read(CHUNK_BYTES)
                if not chunk:
                    break
                if not total:
                    valid = chunk.startswith({"flac": b"fLaC", "ncm": b"CTENFDAM"}.get(extension, b"ID3"))
                    if extension == "mp3" and len(chunk) > 1:
                        valid = valid or chunk[0] == 255 and chunk[1] & 230 == 226
                    if not valid:
                        if extension == "ncm":
                            raise DownloadUnavailable("网易云要求加密保存，但未返回有效的 NCM 文件")
                        raise DownloadUnavailable("下载格式与选择不符，或文件受到保护")
                total += len(chunk)
                if total > size:
                    raise DownloadError("下载长度与官网信息不符")
                digest.update(chunk)
                stream.write(chunk)
                if progress and total < size:
                    now = time.monotonic()
                    if now >= next_update:
                        progress(total, size)
                        next_update = now + .12
            if total != size or (expected_md5 and digest.hexdigest() != str(expected_md5).lower()):
                raise DownloadError("下载文件完整性校验失败")

    def run(self, kind, identifier, directory, format_name, progress, on_saved=None):
        transfer_errors = (OSError, ValueError, HTTPException, GLib.Error)
        completed = skipped = failed = 0
        detail = ""
        saved = None
        try:
            if kind == "playlist":
                name, songs = self.playlist(identifier)
                directory = directory / f"{name} [{identifier}]"
                if directory.is_symlink():
                    raise DownloadError("歌单下载子目录指向符号链接，请选择其它目录")
            else:
                songs = [identifier]
            if not songs:
                return "歌单里没有歌曲"
            directory.mkdir(parents=True, exist_ok=True)
            total = len(songs)
            for offset in range(0, total, 50):
                self.check_cancelled()
                batch = songs[offset:offset + 50]
                try:
                    titles = self.titles(batch)
                except transfer_errors:
                    titles = {}
                for index, song in enumerate(batch, offset):
                    self.check_cancelled()
                    title = titles.get(song, str(song))
                    heading = f"{index + 1}/{total} · {title}"
                    progress(index, total, f"正在准备 {heading}")

                    def transfer(received, size):
                        progress(index + received / size, total, f"正在下载 {heading}\n"
                                 f"{received / 1024**2:.1f} / {size / 1024**2:.1f} MiB")

                    try:
                        saved = self.download(directory, song, title, format_name, transfer)
                        if saved is not None:
                            completed += 1
                            if on_saved:
                                on_saved(str(song))
                            progress(index + 1, total, f"已保存 {heading}")
                        else:
                            skipped += 1
                            if kind == "track":
                                detail = "下载目录里已有这首歌"
                    except DownloadUnavailable as error:
                        skipped += 1
                        detail = str(error)
                    except (DownloadCancelled, LoginRequired):
                        raise
                    except DownloadError as error:
                        failed += 1
                        detail = str(error)
                    except transfer_errors:
                        failed += 1
                        detail = "请检查连接和下载目录"
            if kind == "track":
                return f"已保存\n{saved.name}" if saved else detail
            status = f"已下载 {completed} 首，跳过 {skipped} 首，失败 {failed} 首"
        except DownloadCancelled:
            status = f"下载已取消，已保存 {completed} 首"
        except DownloadError as error:
            status = str(error)
        except transfer_errors:
            status = "下载遇到网络或文件错误，请检查连接和下载目录"
        return f"{status}\n{detail}" if detail else status
