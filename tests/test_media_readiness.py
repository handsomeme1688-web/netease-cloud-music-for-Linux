"""Howler loading, seek preroll and cancellation across track changes."""
from pathlib import Path
import json
import time
import unittest
import gi
for api in ('4.1','4.0'):
    try:gi.require_version('JavaScriptCore',api);break
    except ValueError:pass
from gi.repository import JavaScriptCore as JSC, GLib

FIXTURE=r'''
const location={origin:'https://music.163.com',pathname:'/st/webplayer'};
const window={addEventListener:()=>{}};
const setInterval=()=>1,clearInterval=()=>{};
function Node(){this.paused=true;this.readyState=2;this.src='track-a';this.error=null;this.plays=0;}
Node.prototype.play=function(){this.plays++;this.paused=false;if(!this.stayCurrent)this.readyState=4;return Promise.resolve()};
function Event(type){this.type=type;}
Node.prototype.dispatchEvent=function(event){if(event.type==='canplay'&&this.onCanPlay)this.onCanPlay();};
function Howl(){this._src='track-a';this._state='loaded';this._playLock=false;this._queue=[];this._sprite={__default:[0,90000]};this._sounds=[{_id:1,_seek:0,_node:new Node()}];}
Howl.prototype.load=function(){this._state='loading';return this;};
Howl.prototype.play=function(){const node=this._sounds[0]._node;if(node.readyState>=3)node.play();else{this._playLock=true;this._state='loading';node.onCanPlay=()=>{this._playLock=false;this._state='loaded';};}return 1;};
Howl.prototype.seek=function(value){if(this._state!=='loaded'||this._playLock){this._queue.push({event:'seek',action:()=>this.seek(value)});return this;}this._sounds[0]._seek=value;return this;};
Howl.prototype._clearTimer=function(){this.cleared=true;};
Howl.prototype._loadQueue=function(){this.drained=true;};
'''

class MediaReadinessTests(unittest.TestCase):
    def setUp(self):
        self.context=JSC.Context.new()
        self.evaluate(FIXTURE)
        self.evaluate((Path(__file__).resolve().parents[1]/'assets/media-readiness.js').read_text())
        self.evaluate("window.Howler={_canPlayEvent:'canplaythrough',_howls:[]};window.Howl=Howl;const h=new Howl();window.Howler._howls.push(h);")

    def evaluate(self,source):
        result=self.context.evaluate(source,-1);error=self.context.get_exception()
        self.assertIsNone(error,error.get_message() if error else '')
        return result

    def snapshot(self,source):
        self.evaluate(source)
        until=time.monotonic()+.03
        while time.monotonic()<until:
            while GLib.MainContext.default().pending():GLib.MainContext.default().iteration(False)
            time.sleep(.001)
        return json.loads(self.evaluate("JSON.stringify({event:window.Howler._canPlayEvent,plays:h._sounds[0]._node.plays,state:h._state,lock:h._playLock,seek:h._sounds[0]._seek,queue:h._queue.length,drained:!!h.drained})").to_string())

    def test_library_is_configured_before_first_track(self):
        self.assertEqual(self.snapshot('')['event'],'canplay')

    def test_seek_with_current_data_primes_media_instead_of_deadlocking(self):
        result=self.snapshot('h.play(1)')
        self.assertGreater(result['plays'],0)
        self.assertFalse(result['lock'])
        self.assertEqual(result['state'],'loaded')

    def test_native_play_completion_releases_lock_even_if_ready_state_stays_two(self):
        result=self.snapshot('h._sounds[0]._node.stayCurrent=true;h._sounds[0]._node.duration=90;h.play(1)')
        self.assertGreater(result['plays'],0)
        self.assertFalse(result['lock'])
        self.assertEqual(result['state'],'loaded')

    def test_empty_media_is_not_primed(self):
        result=self.snapshot("h._sounds[0]._node.src='';h.play(1)")
        self.assertEqual(result['plays'],0)

    def test_other_sound_ids_are_not_started(self):
        result=self.snapshot('h.play(999)')
        # The fake original also attempts playback; only an unintended priming
        # request would raise the ready state and make that attempt succeed.
        self.assertEqual(result['plays'],0)

    def test_queued_seek_cannot_follow_a_new_source(self):
        result=self.snapshot("h._state='loading';h.seek(75);const pending=h._queue.shift();h._src='track-b';h._state='loaded';pending.action();")
        self.assertEqual(result['seek'],0)
        self.assertTrue(result['drained'])

    def test_queued_seek_still_runs_for_its_own_source(self):
        result=self.snapshot("h._state='loading';h.seek(75);const pending=h._queue.shift();h._state='loaded';pending.action();")
        self.assertEqual(result['seek'],75)

    def test_reusing_howl_for_new_track_resets_seek_and_play_lock(self):
        result=self.snapshot("h.load();h._src='track-b';h._playLock=true;h._sounds[0]._seek=75;h._queue.push({event:'seek'});h.load();")
        self.assertEqual(result['seek'],0)
        self.assertFalse(result['lock'])
        self.assertEqual(result['queue'],0)
