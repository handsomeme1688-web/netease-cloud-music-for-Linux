from hashlib import md5
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch

import gi

from audio_buffer import CHUNK_BYTES
from music_downloads import (DESKTOP_DOWNLOAD, DOWNLOAD_PATH, FORMATS, DownloadError, DownloadUnavailable,
                             MusicDownloads, downloadable_audio, downloaded_songs, load_preferences)


def permission(song=42, **fields):
    sample = b"fLaC" + b"test"
    return {"code": 200, "data": dict({"id": song, "code": 200, "url": "https://m8.music.126.net/music.flac",
                                      "type": "flac", "size": len(sample), "md5": md5(sample).hexdigest(),
                                      "flag": 0, "payed": 0}, **fields)}


class DownloadTests(unittest.TestCase):
    def test_only_official_plain_download_grants_for_the_requested_format_are_used(self):
        self.assertEqual(downloadable_audio(permission(), 42, "flac")[1], 8)
        for grant, song, format_name in (
            (permission(flag=4), 42, "flac"),
            (permission(flag=32, payed=2), 42, "flac"),
            (permission(code=404), 42, "flac"),
            (permission(freeTrialInfo={"end": 30}), 42, "flac"),
            (permission(url="https://example.org/audio.flac"), 42, "flac"),
            (permission(), 43, "flac"),
            (permission(), 42, "mp3"),
        ):
            with self.assertRaises(DownloadUnavailable):
                downloadable_audio(grant, song, format_name)

    def test_optional_payment_field_does_not_block_a_plain_file(self):
        self.assertEqual(downloadable_audio(permission(payed=None), 42, "flac")[1], 8)
        with self.assertRaisesRegex(DownloadError, "授权信息不完整"):
            downloadable_audio(permission(flag=None), 42, "flac")

    def test_membership_grant_can_download_a_plain_file(self):
        grant = permission(flag=4, payed=1, fee=1, encryptFile=False)
        self.assertEqual(downloadable_audio(grant, 42, "flac")[1], 8)

    def test_single_download_explains_why_no_file_was_saved(self):
        task = MusicDownloads({}, Event())
        task.titles = lambda _: {42: "Song"}
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for grant, expected in (
                (permission(flag=32), "未提供可保存的加密版本"),
                (permission(freeTrialInfo={"end": 30}), "只返回了试听片段"),
            ):
                task.api = lambda *_: grant
                status = task.run("track", 42, directory, "flac", lambda *_: None)
                self.assertIn(expected, status)
                self.assertEqual(list(directory.iterdir()), [])

    def test_desktop_request_uses_the_selected_high_quality(self):
        task = MusicDownloads({}, Event())
        with patch('music_downloads.encode_request', return_value=b'params=fixture') as encode, \
                patch.object(task, 'read_response', return_value={}) as send:
            task.download_grant(42, FORMATS['sky'])
        params, path = encode.call_args.args
        self.assertEqual((path, params['id'], params['level'], params['immerseType']),
                         (DOWNLOAD_PATH, 42, 'sky', 'c51'))
        self.assertEqual(send.call_args.args[0].full_url, DESKTOP_DOWNLOAD)

    def test_high_quality_does_not_accept_a_lower_quality_flac(self):
        with self.assertRaisesRegex(DownloadUnavailable, "超清母带"):
            downloadable_audio(permission(level="lossless"), 42, "jymaster")
        self.assertEqual(downloadable_audio(permission(level="jymaster"), 42, "jymaster")[-1], "flac")

    def test_protected_download_saves_only_the_original_ncm_bytes(self):
        task = MusicDownloads({}, Event())
        sample = b"CTENFDAM" + b"encrypted fixture"
        task.download_grant = lambda *_: permission(
            level="sky", flag=32, encryptFile=True, size=len(sample), md5=md5(sample).hexdigest())

        class Media(BytesIO):
            status = 200

        with TemporaryDirectory() as tmp, patch.object(task.opener, 'open') as open_media:
            directory = Path(tmp)
            open_media.return_value = Media(b"fLaC" + sample[4:])
            with self.assertRaisesRegex(DownloadUnavailable, "要求加密保存"):
                task.download(directory, 42, "Song", "sky")
            self.assertEqual(list(directory.iterdir()), [])
            open_media.return_value = Media(sample)
            path = task.download(directory, 42, "Song", "sky")
            self.assertEqual(path.name, "Song [42] [沉浸环绕声].ncm")
            self.assertEqual(path.read_bytes(), sample)
            self.assertIsNone(task.download(directory, 42, "Song", "sky"))

    def test_playlist_walks_all_ids_and_skips_unavailable_files(self):
        task = MusicDownloads({}, Event())
        songs = [41, 42, 43]

        def api(path, params):
            if path.endswith("/playlist/detail"):
                return {"code": 200, "playlist": {"name": "../Playlist", "trackCount": len(songs),
                                                   "trackIds": [{"id": song} for song in songs]}}
            if path.endswith("/song/detail"):
                return {"code": 200, "songs": [{"id": song, "name": f"Song/{song}"} for song in songs]}
            return permission(params["id"], flag=32 if params["id"] == 42 else 0)

        class Media(BytesIO):
            status = 200

        class Opener:
            def open(self, request, timeout):
                return Media(b"fLaCtest")

        task.api = api
        task.opener = Opener()
        with TemporaryDirectory() as tmp:
            seen = []
            summary = task.run("playlist", 99, Path(tmp), "flac",
                               lambda done, total, message: seen.append((done, total)))
            self.assertIn("已下载 2 首，跳过 1 首，失败 0 首", summary)
            self.assertEqual(seen, [(0, 3), (1, 3), (1, 3), (2, 3), (3, 3)])
            written = list(Path(tmp).rglob("*.flac"))
            self.assertEqual(sorted(path.name for path in written), ["Song_41 [41].flac", "Song_43 [43].flac"])
            self.assertTrue(all(path.read_bytes() == b"fLaCtest" for path in written))
            self.assertEqual(list(Path(tmp).rglob("*.part")), [])

    def test_single_song_reports_byte_progress_then_reaches_full_after_save(self):
        task = MusicDownloads({}, Event())
        task.titles = lambda _: {42: "Song"}
        sample = b"fLaC" + b"\0" * (2 * CHUNK_BYTES - 4)
        task.download_grant = lambda *_: permission(size=len(sample), md5=md5(sample).hexdigest())
        media = BytesIO(sample)
        media.status = 200
        with TemporaryDirectory() as tmp, patch.object(task.opener, "open", return_value=media):
            target = Path(tmp) / "Song [42].flac"
            updates = []

            def progress(done, total, message):
                updates.append((done / total, target.exists()))

            self.assertIn("已保存", task.run("track", 42, target.parent, "flac", progress))
            self.assertEqual(updates, [(0, False), (.5, False), (1, True)])

    def test_invalid_preferences_restore_default(self):
        with TemporaryDirectory() as tmp:
            fallback = Path(tmp) / "Downloads"
            config = Path(tmp) / "downloads.json"
            config.write_text('{"directory": "relative", "format": "flac"}', encoding="utf-8")
            self.assertEqual(load_preferences(config, fallback), (fallback, "mp3"))
            config.write_text(json.dumps({"directory": str(fallback), "format": "jymaster"}), encoding="utf-8")
            self.assertEqual(load_preferences(config, fallback), (fallback, "jymaster"))

    def test_downloaded_status_respects_quality_and_existing_playlist_files(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            playlist = root / "Playlist [99]"
            playlist.mkdir()
            normal = root / "Song [42].flac"
            normal.write_bytes(b"fLaC")
            (root / "Song [43] [超清母带].flac").write_bytes(b"fLaC")
            (playlist / "Song [44] [超清母带].ncm").write_bytes(b"CTENFDAM")
            (playlist / "Song [45] [FLAC].ncm").write_bytes(b"CTENFDAM")
            (playlist / "Song [46] [超清母带].flac.part").write_bytes(b"fLaC")
            (root / "Song [47].flac").symlink_to(normal)
            (root / "Song [48].flac").touch()
            self.assertEqual(downloaded_songs(root, "flac"), {"42", "45"})
            self.assertEqual(downloaded_songs(root, "jymaster"), {"43", "44"})
            normal.unlink()
            self.assertEqual(downloaded_songs(root, "flac"), {"45"})

    def test_right_clicking_the_title_resolves_the_play_button_in_the_same_row(self):
        try:
            gi.require_version("JavaScriptCore", "4.1")
        except ValueError:
            gi.require_version("JavaScriptCore", "4.0")
        from gi.repository import JavaScriptCore

        context = JavaScriptCore.Context.new()
        context.evaluate("""
            const location = {origin:'https://music.163.com', pathname:'/st/webplayer'};
            let rightClick, action;
            class Element {}
            const row = new Element(), title = new Element(), play = new Element();
            row.querySelector = selector => selector === 'button.play-btn' ? play : null;
            title.closest = selector => selector.includes('.tr') ? row : null;
            title.parentElement = row;
            play.__reactFiber$fixture = {memoizedProps:{data:{resourceType:'track',resource:{id:42}}}};
            const document = {addEventListener(type, listener) { rightClick = listener; }};
            const window = {addEventListener() {}, dispatchEvent(event) { action = event.detail; }};
            class CustomEvent { constructor(_, {detail}) { this.detail = detail; } }
            class MutationObserver { observe() {} }
            const setTimeout = () => {};
        """, -1)
        script = Path(__file__).resolve().parents[1] / "assets/download-targets.js"
        context.evaluate(script.read_text(encoding="utf-8"), -1)
        action = context.evaluate("""
            rightClick({isTrusted:true,target:title,clientX:100,clientY:200,preventDefault() {}});
            action;
        """, -1)
        error = context.get_exception()
        self.assertIsNone(error, error.get_message() if error else "")
        self.assertEqual(json.loads(action.to_string()), {"kind": "track", "id": "42", "x": 100, "y": 200})
