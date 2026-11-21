"""Complete native loading, decode routing, cancellation and track ownership."""
from pathlib import Path
import json,time,unittest
import gi
for api in ('4.1','4.0'):
    try:gi.require_version('JavaScriptCore',api);break
    except ValueError:pass
from gi.repository import JavaScriptCore as JSC,GLib
FIXTURE=r'''
class URL{constructor(value){const m=/^(https?):\/\/([^/]+)/.exec(value);if(!m)throw new Error('URL');this.protocol=m[1]+':';this.hostname=m[2];}}
const location={origin:'https://music.163.com',pathname:'/st/webplayer'};
const window={addEventListener:()=>{}};const requests=[],opens=[],released=[];
let clock=0,timerId=0;const timers=new Map();Date.now=()=>clock;
const setInterval=()=>1,clearInterval=()=>{};
const setTimeout=(fn,ms)=>{timers.set(++timerId,{fn,at:clock+ms});return timerId;};
const clearTimeout=id=>timers.delete(id);
function advance(ms){const until=clock+ms;for(;;){const next=[...timers].sort((a,b)=>a[1].at-b[1].at)[0];
 if(!next||next[1].at>until)break;clock=next[1].at;timers.delete(next[0]);next[1].fn();}clock=until;}
class AbortController{constructor(){this.signal={aborted:false};}abort(){this.signal.aborted=true;}}
class XMLHttpRequest{open(method,url){opens.push(url);}send(){this.onload();}abort(){this.aborted=true;}}
window.__musicFetchNativeAudio=(url,signal,progress)=>new Promise((resolve,reject)=>requests.push({url,signal,progress,resolve,reject}));
function Howl(options){this.init(options);}
Howl.prototype.init=function(options){this._src=options.src;this._webAudio=!options.html5;this._state='unloaded';this._queue=[];this.listeners={};return this;};
Howl.prototype.load=function(){this.originalLoads=(this.originalLoads||0)+1;this._src=Array.isArray(this._src)?this._src[0]:this._src;const xhr=new XMLHttpRequest();xhr.open('GET',this._src);xhr.onload=()=>{this._state='loaded';this.emit('load');};xhr.send();return this;};
Howl.prototype.once=function(name,fn){this.listeners[name]=fn;};
Howl.prototype.emit=function(name){const fn=this.listeners[name];delete this.listeners[name];if(fn)fn();};
Howl.prototype._emit=function(name){this.lastEvent=name;};
Howl.prototype.unload=function(){this._state='unloaded';return null;};
Howl.prototype.play=function(){this.played=true;return 1;};
'''

class WebAudioPlaybackTests(unittest.TestCase):
    def setUp(self):
        self.context=JSC.Context.new()
        self.evaluate(FIXTURE)
        self.evaluate((Path(__file__).resolve().parents[1]/'assets/web-audio-playback.js').read_text())
        self.evaluate("window.Howl=Howl;const h=new window.Howl({src:['https://m10.music.126.net/a.mp3'],html5:true});")

    def evaluate(self,source):
        result=self.context.evaluate(source,-1);error=self.context.get_exception()
        self.assertIsNone(error,error.get_message() if error else '')
        return result

    def snapshot(self,source=''):
        self.evaluate(source)
        until=time.monotonic()+.03
        while time.monotonic()<until:
            while GLib.MainContext.default().pending():GLib.MainContext.default().iteration(False)
            time.sleep(.001)
        return json.loads(self.evaluate("JSON.stringify({web:h._webAudio,state:h._state,source:h._src,loads:h.originalLoads||0,requests:requests.length,aborted:requests.map(r=>r.signal.aborted),opens,released,event:h.lastEvent,queue:h._queue})").to_string())

    def complete(self,index=0):
        return self.snapshot('requests[%d].resolve({url:"https://127.0.0.1:9999/token/file%d",release:()=>released.push(%d)});'%(index,index,index))

    def test_music_uses_decoded_samples_instead_of_html5_streaming(self):
        self.assertTrue(self.snapshot()['web'])

    def test_waits_for_complete_native_copy_before_loading(self):
        result=self.snapshot('h.load();h.load();')
        self.assertEqual(result['requests'],1)
        self.assertEqual(result['loads'],0)
        self.assertEqual(result['state'],'loading')

    def test_failed_preload_retries_through_the_normal_download(self):
        result = self.snapshot('window.__musicTakePreload=()=>Promise.resolve(null);h.load();')
        self.assertEqual(result['requests'], 1)
        self.assertEqual(self.complete()['state'], 'loaded')

    def test_routes_only_audio_xhr_and_keeps_requested_source_identity(self):
        self.snapshot('h.load();')
        result=self.complete()
        self.assertEqual(result['opens'],['https://127.0.0.1:9999/token/file0'])
        self.assertEqual(result['source'],'https://m10.music.126.net/a.mp3')
        self.assertEqual(result['state'],'loaded')
        self.assertEqual(result['released'],[0])

    def test_completed_decode_releases_encoded_copy(self):
        self.snapshot('h.load();');self.complete()
        result=self.snapshot('const other=new XMLHttpRequest();other.open("GET","https://m10.music.126.net/a.mp3");')
        self.assertEqual(result['opens'][-1],'https://m10.music.126.net/a.mp3')
        self.assertEqual(result['released'],[0])

    def test_unload_cancels_pending_download_and_rejects_late_result(self):
        self.snapshot('h.load();h.unload();')
        result=self.complete()
        self.assertTrue(result['aborted'][0])
        self.assertEqual(result['loads'],0)
        self.assertEqual(result['released'],[0])

    def test_new_source_cancels_old_loading_transaction(self):
        self.snapshot('h.load();h._src="https://m10.music.126.net/b.mp3";h.load();')
        self.complete(0);result=self.complete(1)
        self.assertEqual(result['loads'],1)
        self.assertEqual(result['source'],'https://m10.music.126.net/b.mp3')
        self.assertTrue(result['aborted'][0])

    def test_download_failure_ends_loading_and_clears_old_requests(self):
        self.snapshot('h.load();h._queue.push({event:"seek"});')
        result=self.snapshot('requests[0].reject(new Error("network"));')
        self.assertEqual(result['state'],'unloaded')
        self.assertEqual(result['queue'],[])
        self.assertEqual(result['event'],'loaderror')

    def test_unrelated_sources_retain_the_sites_chosen_mode(self):
        result=self.snapshot('const other=new window.Howl({src:["https://example.org/sound.mp3"],html5:true});other.load();')
        self.assertEqual(result['requests'],0)
        self.assertEqual(result['opens'],['https://example.org/sound.mp3'])

    def test_active_decoded_track_is_removed_on_unload(self):
        self.snapshot('h.play();')
        self.assertTrue(self.evaluate('window.__musicNativeHowl()===h').to_boolean())
        self.snapshot('h.unload();')
        self.assertTrue(self.evaluate('window.__musicNativeHowl()===null').to_boolean())

    def test_large_download_continues_while_bytes_advance(self):
        result=self.snapshot('h.load();advance(25000);requests[0].progress(1024,90000000);advance(25000);')
        self.assertFalse(result['aborted'][0])

    def test_download_without_progress_times_out(self):
        result=self.snapshot('h.load();advance(30001);')
        self.assertTrue(result['aborted'][0])

    def test_download_has_an_absolute_deadline(self):
        result=self.snapshot('h.load();for(let i=0;i<40;i++){advance(25000);requests[0].progress(i+1,90000000);}')
        self.assertTrue(result['aborted'][0])

    def test_unloaded_download_progress_does_not_restart_its_timer(self):
        self.snapshot('h.load();h.unload();requests[0].progress(1024,90000000);')
        self.assertEqual(self.evaluate('timers.size').to_int32(),0)
