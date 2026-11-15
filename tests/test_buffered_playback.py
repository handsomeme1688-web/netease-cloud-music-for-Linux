"""Stable per-track sources, native media state and bounded cache lifetime."""
import json
from pathlib import Path
import time
import unittest

import gi
for candidate in ('4.1', '4.0'):
    try:
        gi.require_version('JavaScriptCore', candidate)
        break
    except ValueError:
        pass
from gi.repository import JavaScriptCore as JSC, GLib

FIXTURE = r'''
const location={origin:'https://music.163.com',pathname:'/st/webplayer'};
let clock=0;const performance={now:()=>clock};
const timers=[];let timerId=0;
function setTimeout(fn,ms){const id=++timerId;timers.push({id,at:clock+(ms||0),fn,every:0});return id;}
function setInterval(fn,ms){const id=++timerId;timers.push({id,at:clock+ms,fn,every:ms});return id;}
function clearTimeout(id){const i=timers.findIndex(t=>t.id===id);if(i>=0)timers.splice(i,1);}
const clearInterval=clearTimeout;
function advance(ms){const end=clock+ms;for(;;){timers.sort((a,b)=>a.at-b.at);const t=timers[0];
 if(!t||t.at>end)break;clock=t.at;if(t.every)t.at+=t.every;else timers.shift();t.fn();}clock=end;}
const notes=[],created=[],revoked=[],natives=[];
const pageListeners={};
const window={addEventListener:(name,fn)=>pageListeners[name]=fn,webkit:{messageHandlers:{playbackRecovery:{postMessage:v=>notes.push(JSON.parse(v))}}}};
class URL{constructor(source){const m=/^(https?):\/\/([^/]+)/.exec(source);if(!m)throw new Error();
 this.protocol=m[1]+':';this.hostname=m[2];}
 static createObjectURL(blob){const id='blob:fixture-'+created.length;created.push(id);return id;}
 static revokeObjectURL(id){revoked.push(id);}}
class Blob{constructor(chunks){this.size=chunks.reduce((s,c)=>s+c.byteLength,0);}}
class DOMException extends Error{constructor(message,name){super(message);this.name=name;}}
class AbortController{constructor(){this.signal={aborted:false};}abort(){this.signal.aborted=true;}}
class Event{constructor(type){this.type=type;this.isTrusted=false;this.stopped=false;}
 stopImmediatePropagation(){this.stopped=true;}}
window.__musicFetchNativeAudio=(url,signal,progress)=>new Promise((resolve,reject)=>{
 const request={url,signal,progress,resolve,reject,
  complete(bytes){resolve({status:200,headers:{get:k=>k==='Content-Length'?String(bytes):'audio/mpeg'},
   body:{getReader:()=>{let sent=false;return{read:async()=>sent?{done:true}:(sent=true,{done:false,value:{byteLength:bytes}}),
   cancel:async()=>{}};}}});},
  fail(){reject(new Error('native failure'));}};
 natives.push(request);});
class HTMLMediaElement{
 constructor(){this._src='';this._paused=true;this._time=0;this._duration=NaN;this._seeking=false;
  this._ranges=[];this.ended=false;this.error=null;this.readyState=0;this.listeners=[];this.calls=[];}
 get src(){return this._src;}
 set src(value){this._src=value;this.calls.push('src:'+value);this._paused=true;this._time=0;
  this._duration=NaN;this.readyState=0;this._ranges=[];this.error=null;}
 get currentSrc(){return this._src;}
 get currentTime(){return this._time;}
 set currentTime(value){this._time=value;this.calls.push('seek:'+value);}
 get paused(){return this._paused;}
 get duration(){return this._duration;}
 get seeking(){return this._seeking;}
 get buffered(){const r=this._ranges;return{length:r.length,start:i=>r[i][0],end:i=>r[i][1]};}
 removeAttribute(name){if(name==='src'){this._src='';this.calls.push('remove-src');}}
 load(){this.calls.push('load');}
 play(){this.calls.push('play');this._paused=false;if(this.deferPlay)return new Promise((ok,fail)=>{this.failPlay=fail;});const e=new Event('playing');e.isTrusted=true;this.dispatchEvent(e);return Promise.resolve();}
 pause(){this.calls.push('pause');this._paused=true;}
 addEventListener(type,fn,capture){this.listeners.push({type,fn,capture:!!capture});}
 removeEventListener(type,fn,capture){const i=this.listeners.findIndex(l=>l.type===type&&l.fn===fn&&l.capture===!!capture);
  if(i>=0)this.listeners.splice(i,1);}
 dispatchEvent(event){const list=this.listeners.filter(l=>l.type===event.type);
  for(const l of list.filter(l=>l.capture).concat(list.filter(l=>!l.capture))){
   if(event.stopped)break;if(this.listeners.includes(l))l.fn.call(this,event);}return true;}}
// The media engine finishing a load: trusted readiness events.
function engineReady(audio,duration,ranges){audio._duration=duration;audio.readyState=4;
 audio._ranges=ranges||[[0,duration]];
 for(const type of ['durationchange','loadedmetadata','loadeddata','canplay','canplaythrough']){
  const e=new Event(type);e.isTrusted=true;audio.dispatchEvent(e);}}
function engineError(audio){audio.error={code:4};const e=new Event('error');e.isTrusted=true;audio.dispatchEvent(e);}
const site=[];
// Like Howler: the load listener reads the duration once, then removes itself.
function siteListens(audio){
 const loaded=()=>{site.push('canplaythrough:'+audio.duration);audio.removeEventListener('canplaythrough',loaded,false);};
 audio.addEventListener('canplaythrough',loaded,false);
 for(const type of ['error','ended'])audio.addEventListener(type,()=>site.push(type+':'),false);}
const CDN='https://m10.music.126.net/one.mp3?token=1';
const audio=new HTMLMediaElement();
siteListens(audio);
'''


class BufferedPlaybackTests(unittest.TestCase):
    def setUp(self):
        self.context = JSC.Context.new()
        self.evaluate(FIXTURE)
        self.evaluate("const originalMedia = Object.fromEntries(['currentTime','paused','duration','buffered','seeking'].map(name => [name, Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype,name)]));")
        self.evaluate((Path(__file__).resolve().parents[1] / 'assets/buffered-playback.js').read_text())

    def evaluate(self, source):
        value = self.context.evaluate(source, -1)
        error = self.context.get_exception()
        self.assertIsNone(error, error.get_message() if error else '')
        return value

    def run_js(self, source=''):
        self.evaluate(source)
        until = time.monotonic() + .03
        context = GLib.MainContext.default()
        while time.monotonic() < until:
            while context.pending(): context.iteration(False)
            time.sleep(.001)
        return json.loads(self.evaluate('''JSON.stringify({raw:audio._src,visible:audio.src,
            time:audio.currentTime,paused:audio.paused,duration:audio.duration,calls:audio.calls,site,
            notes:notes.map(n=>n.event+(n.reason?':'+n.reason:'')),natives:natives.length,
            aborted:natives.map(n=>n.signal.aborted),created,revoked});''').to_string())

    def start_track(self):
        return self.run_js('audio.src=CDN;audio.load();')

    def copy_playing(self):
        self.start_track()
        self.run_js('natives[0].complete(3);')
        return self.run_js('engineReady(audio,90);audio.play();audio._time=30;')

    def test_complete_copy_is_selected_before_playback(self):
        state=self.start_track()
        self.assertEqual(state['raw'],'')
        self.assertEqual(state['natives'],1)
        self.run_js('natives[0].complete(3);')
        state=self.run_js('engineReady(audio,90);audio.play();')
        self.assertEqual(state['raw'],'blob:fixture-0')
        self.assertEqual(state['site'],['canplaythrough:90'])
        self.assertFalse(state['paused'])

    def test_waiting_play_does_not_fake_the_paused_property(self):
        self.start_track()
        state=self.run_js('audio.play().then(()=>site.push("resolved"),e=>site.push(e.name));')
        self.assertTrue(state['paused'])
        self.assertNotIn('play',state['calls'])
        self.run_js('natives[0].complete(3);')
        state=self.run_js('engineReady(audio,90);')
        self.assertIn('resolved',state['site'])

    def test_native_media_properties_are_not_replaced(self):
        self.copy_playing()
        state=self.run_js('audio._time=43.2;audio._duration=90.1;advance(20000);')
        self.assertEqual(state['time'],43.2)
        self.assertEqual(state['duration'],90.1)
        self.assertTrue(self.evaluate("Object.keys(originalMedia).every(name => Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype,name).get === originalMedia[name].get)").to_boolean())

    def test_slow_download_is_given_the_actual_wait_budget(self):
        self.start_track()
        state=self.run_js('advance(1000);natives[0].progress(100000,10000000);')
        self.assertEqual(state['raw'],'')
        state=self.run_js('natives[0].complete(10000000);')
        self.assertEqual(state['raw'],'blob:fixture-0')

    def test_timeout_cancels_download_and_ignores_late_completion(self):
        self.start_track()
        state=self.run_js('advance(4000);')
        self.assertEqual(state['raw'],self.evaluate('CDN').to_string())
        self.assertTrue(state['aborted'][0])
        state=self.run_js('natives[0].complete(3);advance(10000);')
        self.assertEqual(state['created'],[])
        self.assertEqual(state['raw'],self.evaluate('CDN').to_string())

    def test_pause_does_not_change_selected_resource_or_progress(self):
        self.copy_playing()
        state=self.run_js('audio.pause();advance(30000);')
        self.assertEqual(state['raw'],'blob:fixture-0')
        self.assertEqual(state['time'],30)
        self.assertTrue(state['paused'])
        self.assertEqual(state['revoked'],[])

    def test_stream_stall_and_low_buffer_do_not_switch_sources(self):
        self.start_track()
        self.run_js('advance(4000);engineReady(audio,90,[[0,31]]);audio.play();audio._time=30;')
        state=self.run_js('natives[0].complete(3);audio.readyState=2;advance(30000);')
        self.assertEqual(state['raw'],self.evaluate('CDN').to_string())
        self.assertEqual(state['time'],30)
        self.assertEqual(state['created'],[])

    def test_pause_cancels_waiting_play_without_late_auto_resume(self):
        self.start_track()
        self.run_js('audio.play().catch(e=>site.push(e.name));audio.pause();')
        state=self.run_js('natives[0].complete(3);engineReady(audio,90);')
        self.assertTrue(state['paused'])
        self.assertNotIn('play',state['calls'])
        self.assertIn('AbortError',state['site'])

    def test_track_change_cancels_download_and_pending_play(self):
        self.start_track()
        self.run_js('audio.play().catch(e=>site.push(e.name));audio.src="https://m10.music.126.net/two.mp3";')
        state=self.run_js('natives[0].complete(3);')
        self.assertTrue(state['aborted'][0])
        self.assertEqual(state['created'],[])
        self.assertIn('AbortError',state['site'])

    def test_failed_or_partial_audio_falls_back_once(self):
        self.start_track()
        state=self.run_js('natives[0].resolve({status:206});')
        self.assertEqual(state['raw'],self.evaluate('CDN').to_string())
        self.assertEqual(state['created'],[])

    def test_cache_budget_counts_pending_downloads(self):
        self.start_track()
        self.run_js('natives[0].progress(1,40*1024*1024);const second=new HTMLMediaElement();second.src="https://m10.music.126.net/two.mp3";')
        self.run_js('natives[1].progress(1,40*1024*1024);')
        self.assertEqual(self.evaluate('second._src').to_string(),'https://m10.music.126.net/two.mp3')
        self.assertTrue(self.evaluate('natives[1].signal.aborted').to_boolean())

    def test_paused_selected_copy_is_pinned_when_cache_is_full(self):
        self.start_track()
        self.run_js('natives[0].complete(40*1024*1024);')
        self.run_js('engineReady(audio,90);audio.pause();const second=new HTMLMediaElement();second.src="https://m10.music.126.net/two.mp3";')
        state=self.run_js('natives[1].progress(1,40*1024*1024);')
        self.assertEqual(state['revoked'],[])
        self.assertEqual(state['raw'],'blob:fixture-0')

    def test_changing_source_releases_the_previous_copy(self):
        self.copy_playing()
        state=self.run_js('audio.src="data:audio/wav;base64,AAAA";')
        self.assertEqual(state['revoked'],['blob:fixture-0'])
        self.assertEqual(state['raw'],'data:audio/wav;base64,AAAA')

    def test_blob_error_before_start_falls_back_without_retry_loop(self):
        self.start_track()
        self.run_js('natives[0].complete(3);')
        state=self.run_js('engineError(audio);')
        self.assertEqual(state['raw'],self.evaluate('CDN').to_string())
        self.assertEqual(len(state['created']),1)
        self.assertEqual(state['site'],[])
        state=self.run_js('engineError(audio);')
        self.assertEqual(state['site'],['error:'])

    def test_blob_error_after_playback_is_not_hidden_or_restarted(self):
        self.copy_playing()
        state=self.run_js('engineError(audio);advance(30000);')
        self.assertEqual(state['raw'],'blob:fixture-0')
        self.assertEqual(state['time'],30)
        self.assertIn('error:',state['site'])

    def test_initial_readiness_waits_for_true_duration(self):
        self.start_track()
        self.run_js('natives[0].complete(3);')
        state=self.run_js('engineReady(audio,0);')
        self.assertEqual(state['site'],[])
        self.assertEqual(state['duration'],0)
        state=self.run_js('audio._duration=90.07;advance(40);')
        self.assertEqual(state['site'],['canplaythrough:90.07'])

    def test_same_source_load_uses_same_copy(self):
        self.copy_playing()
        state=self.run_js('audio.src=CDN;audio.load();')
        self.assertEqual(state['natives'],1)
        self.assertEqual(state['raw'],'blob:fixture-0')
        self.assertEqual(state['revoked'],[])

    def test_initial_copy_loading_has_one_recovery_owner(self):
        self.start_track()
        self.run_js('natives[0].complete(3);')
        self.assertFalse(self.evaluate('window.__musicPlaybackManaged(audio)').to_boolean())
        self.run_js('engineReady(audio,90);audio.play();')
        self.assertFalse(self.evaluate('window.__musicPlaybackManaged(audio)').to_boolean())

    def test_slow_initial_metadata_does_not_switch_a_copy_source(self):
        self.start_track()
        self.run_js('natives[0].complete(3);')
        state=self.run_js('advance(2100);')
        self.assertEqual(state['raw'],'blob:fixture-0')
        self.assertEqual(state['revoked'],[])

    def test_sources_set_outside_the_js_setter_are_recognized(self):
        state=self.run_js('audio._src=CDN;audio.load();')
        self.assertEqual(state['natives'],1)
        self.assertEqual(state['raw'],'')

    def test_attribute_source_change_invalidates_previous_cache(self):
        self.copy_playing()
        state=self.run_js('audio._src="https://m10.music.126.net/two.mp3";audio.load();')
        self.assertEqual(state['natives'],2)
        self.assertEqual(state['revoked'],['blob:fixture-0'])

    def test_unrelated_sources_and_empty_probes_use_native_methods(self):
        state=self.run_js('audio.src="https://example.com/a.mp3";audio.load();audio.play();')
        self.assertEqual(state['natives'],0)
        self.assertIn('play',state['calls'])

    def test_page_unload_releases_copies_and_pending_downloads(self):
        self.copy_playing()
        self.run_js('const second=new HTMLMediaElement();second.src="https://m10.music.126.net/two.mp3";')
        state=self.run_js('pageListeners.pagehide({persisted:false});')
        self.assertEqual(state['revoked'],['blob:fixture-0'])
        self.assertTrue(state['aborted'][1])

    def test_failed_initial_copy_keeps_play_pending_until_stream_starts(self):
        self.start_track()
        self.run_js('audio.deferPlay=true;audio.play().then(()=>site.push("resolved"),e=>site.push(e.name));natives[0].complete(3);')
        self.run_js('audio.deferPlay=false;engineError(audio);audio.failPlay({name:"NotSupportedError"});')
        state=self.run_js('engineReady(audio,90);')
        self.assertIn('resolved',state['site'])
        self.assertNotIn('NotSupportedError',state['site'])
        self.assertEqual(state['raw'],self.evaluate('CDN').to_string())

    def test_pause_cancels_pending_initial_copy_fallback_play(self):
        self.start_track()
        self.run_js('audio.deferPlay=true;audio.play().catch(()=>{});natives[0].complete(3);')
        state=self.run_js('audio.pause();audio.deferPlay=false;engineError(audio);audio.failPlay({name:"AbortError"});')
        self.assertTrue(state['paused'])
        self.assertEqual(state['calls'].count('play'),1)


if __name__ == '__main__':
    unittest.main()
