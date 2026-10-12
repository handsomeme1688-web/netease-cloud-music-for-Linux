"""Playback policies, stalled media and replacement of a failed session."""
import importlib.util
import json
import time
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('playback_app', Path(__file__).resolve().parents[1] / 'app.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)
app.gi.require_version('JavaScriptCore', app.WEBKIT_API)
from gi.repository import JavaScriptCore as JSC

FAKE_MEDIA = r'''
let now = 0, identifier = 0;
const intervals = new Map(), timeouts = new Map(), messages = [], pageListeners = {};
Date.now = () => now;
const setInterval = callback => {intervals.set(++identifier, callback);return identifier;};
const clearInterval = id => intervals.delete(id);
const setTimeout = (callback, delay) => {timeouts.set(++identifier, {callback, due: now + delay});return identifier;};
const clearTimeout = id => timeouts.delete(id);
const tick = milliseconds => {
 now += milliseconds;
 for (const [id, timer] of Array.from(timeouts)) if(timer.due <= now) {timeouts.delete(id);timer.callback();}
 for (const callback of Array.from(intervals.values())) callback();
};
const window = {webkit: {messageHandlers: {playbackRecovery: {postMessage: value => messages.push(JSON.parse(value).event)}}},
 addEventListener: (event, callback) => {pageListeners[event] = callback;}};
class HTMLMediaElement {
 constructor() {this.src='track-one';this.currentSrc=this.src;this.currentTime=0;this.readyState=4;
  this.paused=true;this.ended=false;this.seeking=false;this.error=null;this.playCalls=0;this.loadCalls=0;
  this.listeners=new Map();this.deferred=false;this.pending=[];}
 addEventListener(event, callback) {if(!this.listeners.has(event))this.listeners.set(event,new Set());this.listeners.get(event).add(callback);}
 removeEventListener(event, callback) {if(this.listeners.has(event))this.listeners.get(event).delete(callback);}
 emit(event) {for(const callback of Array.from(this.listeners.get(event)||[]))callback();}
 play() {this.playCalls++;this.paused=false;this.emit('playing');
  if(this.realPromise)return new Promise((ok,fail)=>this.pending.push({ok,fail}));
  return {then: (ok, fail) => {if(this.deferred)this.pending.push({ok,fail});else ok();}};}
 pause() {this.paused=true;this.emit('pause');}
 load() {if(this.abortPendingOnLoad){for(const pending of this.pending.splice(0))pending.fail({name:'AbortError'});}
  this.loadCalls++;this.paused=true;this.currentTime=0;this.readyState=0;this.emit('pause');}
 ready() {this.readyState=4;this.emit('canplay');}
}
const audio = new HTMLMediaElement();
'''

class StalledPlaybackTests(unittest.TestCase):
    def setUp(self):
        self.context = JSC.Context.new()
        self.evaluate(FAKE_MEDIA)
        source = Path(__file__).resolve().parents[1] / 'assets/playback-recovery.js'
        self.evaluate(source.read_text())

    def evaluate(self, source):
        value = self.context.evaluate(source, -1)
        exception = self.context.get_exception()
        self.assertIsNone(exception, exception.get_message() if exception else '')
        return value

    def snapshot(self, source=''):
        self.evaluate(source)
        deadline=time.monotonic()+0.03
        context=app.GLib.MainContext.default()
        while time.monotonic()<deadline:
            while context.pending():context.iteration(False)
            time.sleep(0.001)
        return json.loads(self.evaluate('''JSON.stringify({plays:audio.playCalls,loads:audio.loadCalls,position:audio.currentTime,
        paused:audio.paused,messages:messages,timeouts:timeouts.size});''').to_string())

    def test_progress_and_short_buffering_do_not_reload(self):
        state = self.snapshot('audio.play();for(let i=0;i<40;i++){audio.currentTime+=1;tick(1000);}tick(14000)')
        self.assertEqual(state['loads'], 0)
        self.assertEqual(state['plays'], 1)

    def test_stalled_track_recovers_at_its_position(self):
        state = self.snapshot('audio.play();audio.currentTime=42;tick(1000);tick(15000);audio.ready()')
        self.assertEqual(state['loads'], 1)
        self.assertEqual(state['plays'], 2)
        self.assertEqual(state['position'], 42)
        self.assertFalse(state['paused'])
        self.assertEqual(state['timeouts'], 0)

    def test_pausing_during_retry_prevents_resume(self):
        state = self.snapshot('audio.play();tick(15000);audio.pause();audio.ready();tick(20000)')
        self.assertEqual(state['plays'], 1)
        self.assertTrue(state['paused'])
        self.assertEqual(state['timeouts'], 0)
        self.assertNotIn('failed', state['messages'])

    def test_paused_and_finished_tracks_are_not_restarted(self):
        for ending in ('audio.pause()', "audio.ended=true;audio.emit('ended')"):
            with self.subTest(ending=ending):
                self.setUp()
                state = self.snapshot('audio.play();' + ending + ';tick(60000)')
                self.assertEqual(state['loads'], 0)
                self.assertEqual(state['plays'], 1)

    def test_retries_are_bounded_for_one_source(self):
        state = self.snapshot('audio.play();tick(15000);audio.ready();tick(15000);audio.ready();tick(15000);tick(60000)')
        self.assertEqual(state['loads'], 2)
        self.assertEqual(state['plays'], 3)
        self.assertEqual(state['messages'].count('failed'), 1)

    def test_retry_that_never_loads_reports_failure_once(self):
        state = self.snapshot('audio.play();tick(15000);tick(12000);tick(60000)')
        self.assertEqual(state['loads'], 1)
        self.assertEqual(state['messages'].count('failed'), 1)
        self.assertEqual(state['timeouts'], 0)

    def test_loading_retry_does_not_start_paused_media(self):
        state = self.snapshot('audio.load();tick(15000);audio.ready()')
        self.assertEqual(state['plays'], 0)
        self.assertTrue(state['paused'])
        self.assertEqual(state['loads'], 2)

    def test_changing_tracks_invalidates_late_retry_failure(self):
        state = self.snapshot('''audio.play();tick(15000);audio.deferred=true;audio.ready();
        const previous=audio.pending.pop();audio.src='track-two';audio.load();audio.deferred=false;
        audio.ready();audio.play();previous.fail();audio.currentTime=2;tick(1000);''')
        self.assertFalse(state['paused'])
        self.assertNotIn('failed', state['messages'])

    def test_seek_has_a_longer_grace_period(self):
        state = self.snapshot('audio.play();audio.seeking=true;tick(15000)')
        self.assertEqual(state['loads'], 0)
        state = self.snapshot('tick(15000)')
        self.assertEqual(state['loads'], 1)

    def test_page_unload_cancels_pending_recovery(self):
        state = self.snapshot("audio.play();tick(15000);pageListeners.pagehide();audio.ready();tick(60000)")
        self.assertEqual(state['plays'], 1)
        self.assertEqual(state['timeouts'], 0)
        self.assertNotIn('failed', state['messages'])

    def test_media_errors_report_without_unbounded_retries(self):
        state = self.snapshot("audio.play();audio.error={code:2};audio.emit('error');tick(60000)")
        self.assertEqual(state['loads'], 0)
        self.assertEqual(state['messages'].count('failed'), 1)

    def test_empty_audio_pool_probes_do_not_report_playback_failure(self):
        state = self.snapshot("audio.src='';audio.currentSrc='';audio.querySelector=()=>null;audio.play();audio.error={code:4};audio.emit('error');tick(60000)")
        self.assertEqual(state['loads'], 0)
        self.assertEqual(state['messages'], [])

    def test_pending_play_resolves_after_our_reload_instead_of_reporting_abort(self):
        self.evaluate("audio.realPromise=true;audio.abortPendingOnLoad=true;audio.play().then(()=>messages.push('request-resolved'),e=>messages.push(e.name));tick(15000)")
        state = self.snapshot("audio.ready();audio.pending.pop().ok()")
        self.assertIn('request-resolved', state['messages'])
        self.assertNotIn('AbortError', state['messages'])

    def test_user_pause_rejects_pending_recovery_without_restarting(self):
        self.evaluate("audio.realPromise=true;audio.abortPendingOnLoad=true;audio.play().then(()=>messages.push('request-resolved'),e=>messages.push(e.name));tick(15000)")
        state = self.snapshot("audio.pause();audio.ready()")
        self.assertIn('AbortError', state['messages'])
        self.assertNotIn('request-resolved', state['messages'])
        self.assertEqual(state['plays'], 1)

    def test_returning_to_cached_page_restores_monitor(self):
        state = self.snapshot("audio.play();pageListeners.pagehide();pageListeners.pageshow();audio.play();tick(15000);audio.ready()")
        self.assertEqual(state['loads'], 1)
        self.assertEqual(state['plays'], 3)


class PlaybackPolicyTests(unittest.TestCase):
    @unittest.skipUnless(hasattr(app.WebKit2, 'WebsitePolicies'), 'Policies require WebKitGTK 2.30')
    def test_modern_webview_allows_asynchronous_music(self):
        context = object()
        with patch.object(app.WebKit2, 'WebView') as view:
            app.create_webview(context)
            policies = view.call_args.kwargs['website_policies']
            self.assertEqual(policies.get_autoplay_policy(), app.WebKit2.AutoplayPolicy.ALLOW)
            self.assertIs(view.call_args.kwargs['web_context'], context)

    def test_related_view_keeps_its_context(self):
        parent = object()
        with patch.object(app.WebKit2, 'WebView') as view:
            app.create_webview(object(), parent)
            self.assertIs(view.call_args.kwargs['related_view'], parent)
            self.assertNotIn('web_context', view.call_args.kwargs)

    def test_older_api_does_not_receive_unsupported_policy(self):
        api = SimpleNamespace(WebView=Mock())
        context = object()
        with patch.object(app, 'WebKit2', api):
            app.create_webview(context)
        api.WebView.assert_called_once_with(web_context=context)

    @unittest.skipUnless(hasattr(app.WebKit2, 'WebsitePolicies'), 'Policies require WebKitGTK 2.30')
    def test_navigation_allows_music_and_denies_external_autoplay(self):
        for uri, expected in ((app.HOME_URL, app.WebKit2.AutoplayPolicy.ALLOW),
                              ('https://example.org/', app.WebKit2.AutoplayPolicy.DENY)):
            with self.subTest(uri=uri):
                decision = SimpleNamespace(get_navigation_action=lambda: SimpleNamespace(
                    get_request=lambda: SimpleNamespace(get_uri=lambda: uri)),use_with_policies=Mock())
                self.assertTrue(app.MusicWindow.decide_policy(object(), None, decision,
                                app.WebKit2.PolicyDecisionType.NAVIGATION_ACTION))
                policy = decision.use_with_policies.call_args.args[0]
                self.assertEqual(policy.get_autoplay_policy(), expected)

    def test_cancelled_requests_do_not_offer_recovery(self):
        window = SimpleNamespace(get_window=lambda: True,
                                 webview=SimpleNamespace(get_uri=lambda: app.HOME_URL),
                                 playback_notice=Mock())
        error = SimpleNamespace(matches=lambda _domain, code: code == app.WebKit2.NetworkError.CANCELLED)
        app.MusicWindow.playback_resource_failed(window, None, error)
        window.playback_notice.show.assert_not_called()
        error = SimpleNamespace(matches=lambda _domain, code: code == app.WebKit2.NetworkError.FAILED)
        app.MusicWindow.playback_resource_failed(window, None, error)
        window.playback_notice.show.assert_called_once_with()

    def test_resource_monitor_ignores_cover_art_and_unrelated_hosts(self):
        window = SimpleNamespace(playback_resource_failed=Mock())
        for uri, expected in (
                ('https://m10.music.126.net/track.mp3?temporary=value', True),
                ('https://music.163.com/weapi/song/enhance/player/url/v1', True),
                ('https://p3.music.126.net/cover.jpg', False),
                ('https://example.org/track.mp3', False)):
            with self.subTest(uri=uri):
                resource = Mock()
                request = SimpleNamespace(get_uri=lambda: uri)
                app.MusicWindow.playback_resource_started(window, None, resource, request)
                self.assertEqual(resource.connect.called, expected)

    def test_deep_recovery_replaces_session_and_preserves_state(self):
        window = SimpleNamespace(webview=SimpleNamespace(stop_loading=Mock()),destroy=Mock())
        application = SimpleNamespace(main_window=window,hold=Mock(),release=Mock(),save_state=Mock(),
            stop_login_watch=Mock(),get_windows=lambda:[window],create_web_context=Mock(),do_activate=Mock())
        app.MusicApplication.recover_player(application)
        application.save_state.assert_called_once_with(window)
        window.webview.stop_loading.assert_called_once_with()
        window.destroy.assert_called_once_with()
        application.create_web_context.assert_called_once_with()
        application.do_activate.assert_called_once_with()
        application.hold.assert_called_once_with()
        application.release.assert_called_once_with()
        self.assertFalse(application._recovering_player)

    def test_recovery_failure_releases_application_hold(self):
        window = SimpleNamespace(webview=SimpleNamespace(stop_loading=Mock()),destroy=Mock())
        application = SimpleNamespace(main_window=window,hold=Mock(),release=Mock(),save_state=Mock(),
            stop_login_watch=Mock(),get_windows=lambda:[window],create_web_context=Mock(side_effect=RuntimeError),do_activate=Mock())
        with self.assertRaises(RuntimeError):app.MusicApplication.recover_player(application)
        application.release.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
