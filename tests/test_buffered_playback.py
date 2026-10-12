"""Full audio buffering, normal streaming fallback and cancelled play requests."""
import json
from pathlib import Path
import time
import unittest

import gi
api = None
for candidate in ('4.1', '4.0'):
    try:
        gi.require_version('JavaScriptCore', candidate)
        api = candidate
        break
    except ValueError:
        pass
from gi.repository import JavaScriptCore as JSC, GLib

FIXTURE = r'''
const location={origin:'https://music.163.com',pathname:'/st/webplayer'};
const events=[],requests=[],created=[],revoked=[];
const window={addEventListener:()=>{}};
class URL {
 constructor(source){const match=/^(https?):\/\/([^/]+)/.exec(source);if(!match)throw new Error();
 this.protocol=match[1]+':';this.hostname=match[2];}
 static createObjectURL(blob){const id='blob:fixture-'+created.length;created.push({id,size:blob.size});return id;}
 static revokeObjectURL(id){revoked.push(id);}
}
class Blob {constructor(chunks){this.size=chunks.reduce((sum,value)=>sum+value.byteLength,0);}}
class DOMException extends Error {constructor(message,name){super(message);this.name=name;}}
class AbortController {constructor(){this.signal={};}abort(){this.signal.aborted=true;}}
const setTimeout=()=>1,clearTimeout=()=>{};
const fetch=(source,options)=>new Promise((resolve,reject)=>requests.push({source,options,resolve,reject}));
const complete=(index,bytes=3,declared=bytes,status=200)=>{
 let sent=false;const request=requests[index];request.resolve({status,
 headers:{get:key=>key==='Content-Length'?String(declared):'audio/mpeg'},
 body:{getReader:()=>({read:async()=>sent?{done:true}:(sent=true,{done:false,value:{byteLength:bytes}}),
 cancel:async()=>events.push('cancel-body')})}});
};
class HTMLMediaElement {
 constructor(){this.src='https://m10.music.126.net/one.mp3';
 this.paused=true;this.ended=false;this.plays=0;this.loads=0;}
 get src(){return this._src||'';}
 set src(value){this._src=value;}
 get currentSrc(){return this._src||'';}
 play(){this.plays++;this.paused=false;return Promise.resolve();}
 pause(){this.paused=true;}
 load(){this.loads++;this.paused=true;}
}
const originalSource=Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype,'src').get;
const audio=new HTMLMediaElement();
const play=element=>element.play().then(()=>events.push('played'),error=>events.push(error.name));
'''


class BufferedPlaybackTests(unittest.TestCase):
    def setUp(self):
        self.context = JSC.Context.new()
        self.evaluate(FIXTURE)
        source = (Path(__file__).resolve().parents[1] / 'assets/buffered-playback.js').read_text()
        self.evaluate(source)

    def evaluate(self, source):
        value = self.context.evaluate(source, -1)
        error = self.context.get_exception()
        self.assertIsNone(error, error.get_message() if error else '')
        return value

    def snapshot(self, source=''):
        self.evaluate(source)
        until = time.monotonic() + .03
        context = GLib.MainContext.default()
        while time.monotonic() < until:
            while context.pending():
                context.iteration(False)
            time.sleep(.001)
        return json.loads(self.evaluate('''JSON.stringify({events,source:originalSource.call(audio),visibleSource:audio.src,plays:audio.plays,
        loads:audio.loads,requests:requests.length,created,revoked});''').to_string())

    def test_background_buffer_does_not_delay_native_play(self):
        pending = self.snapshot('audio.load();play(audio)')
        self.assertEqual(pending['plays'], 1)
        self.assertEqual(pending['requests'], 1)
        self.snapshot('complete(0)')
        state = self.snapshot('audio.load()')
        self.assertEqual(state['plays'], 1)
        self.assertEqual(state['source'], 'blob:fixture-0')
        self.assertEqual(state['visibleSource'], 'https://m10.music.126.net/one.mp3')
        self.assertEqual(state['created'][0]['size'], 3)

    def test_duplicate_play_requests_share_download_and_both_resolve(self):
        self.snapshot('play(audio);play(audio)')
        state = self.snapshot('complete(0)')
        self.assertEqual(state['requests'], 1)
        self.assertEqual(state['events'], ['played', 'played'])

    def test_pause_during_background_download_does_not_resume(self):
        self.snapshot('play(audio);audio.pause()')
        state = self.snapshot('complete(0)')
        self.assertEqual(state['plays'], 1)
        self.assertEqual(state['events'], ['played'])

    def test_changing_track_drops_old_download(self):
        self.snapshot("play(audio);audio.src='https://m10.music.126.net/two.mp3';audio.load();play(audio)")
        state = self.snapshot('complete(0)')
        self.assertEqual(state['plays'], 2)
        self.assertEqual(state['created'], [])
        state = self.snapshot('complete(1)')
        self.assertEqual(state['plays'], 2)
        self.assertEqual(state['events'], ['played', 'played'])

    def test_cors_failure_keeps_normal_streaming(self):
        self.snapshot('play(audio)')
        state = self.snapshot('requests[0].reject(new TypeError())')
        self.assertEqual(state['plays'], 1)
        self.assertEqual(state['source'], 'https://m10.music.126.net/one.mp3')
        self.assertEqual(state['created'], [])

    def test_partial_response_is_not_treated_as_complete_audio(self):
        for status, declared in ((206, 3), (200, 4)):
            with self.subTest(status=status, declared=declared):
                self.setUp()
                self.snapshot('play(audio)')
                state = self.snapshot('complete(0,3,%s,%s)' % (declared, status))
                self.assertEqual(state['created'], [])
                self.assertEqual(state['plays'], 1)

    def test_oversized_audio_falls_back_without_creating_blob(self):
        self.snapshot('play(audio)')
        state = self.snapshot('complete(0,3,100000000)')
        self.assertEqual(state['created'], [])
        self.assertEqual(state['plays'], 1)

    def test_unknown_length_is_bounded_while_reading(self):
        self.snapshot('play(audio)')
        state = self.snapshot('complete(0,100000000,0)')
        self.assertEqual(state['created'], [])
        self.assertIn('cancel-body', state['events'])
        self.assertEqual(state['plays'], 1)

    def test_other_hosts_and_empty_probes_use_original_play(self):
        for source in ('', 'data:audio/wav;base64,AAAA', 'https://m10.music.126.net.example.com/a.mp3'):
            with self.subTest(source=source):
                self.setUp()
                state = self.snapshot('audio.src=%s;play(audio)' % json.dumps(source))
                self.assertEqual(state['requests'], 0)
                self.assertEqual(state['plays'], 1)

    def test_replaying_cached_audio_needs_no_new_request(self):
        self.snapshot('play(audio)')
        self.snapshot('complete(0)')
        state = self.snapshot('audio.pause();audio.load();play(audio)')
        self.assertEqual(state['requests'], 1)
        self.assertEqual(state['plays'], 2)

    def test_site_reassigning_same_source_keeps_complete_buffer(self):
        self.snapshot('play(audio)')
        self.snapshot('complete(0)')
        state = self.snapshot('audio.pause();audio.src=audio.src;audio.load();play(audio)')
        self.assertEqual(state['requests'], 1)
        self.assertEqual(state['source'], 'blob:fixture-0')
        self.assertEqual(state['plays'], 2)

    def test_evicted_track_downloads_again_without_using_revoked_url(self):
        self.snapshot('play(audio)')
        self.snapshot('complete(0);audio.load()')
        self.snapshot("audio.pause();const second=new HTMLMediaElement();second.src='https://m10.music.126.net/two.mp3';play(second)")
        self.snapshot('complete(1)')
        self.snapshot("second.pause();const third=new HTMLMediaElement();third.src='https://m10.music.126.net/three.mp3';play(third)")
        state = self.snapshot('complete(2)')
        self.assertIn('blob:fixture-0', state['revoked'])
        self.snapshot('play(audio)')
        self.snapshot('complete(3)')
        state = self.snapshot('audio.load()')
        self.assertEqual(state['requests'], 4)
        self.assertEqual(state['source'], 'blob:fixture-3')
        self.assertEqual(state['plays'], 2)

    def test_busy_cache_keeps_streaming_without_unbounded_blobs(self):
        self.snapshot('play(audio)')
        self.snapshot('complete(0,40000000)')
        self.snapshot("const second=new HTMLMediaElement();second.src='https://m10.music.126.net/two.mp3';play(second)")
        state = self.snapshot('complete(1,40000000)')
        self.assertEqual(len(state['created']), 1)
        self.assertEqual(state['revoked'], [])
        self.assertEqual(state['events'], ['played', 'played'])


if __name__ == '__main__':
    unittest.main()
