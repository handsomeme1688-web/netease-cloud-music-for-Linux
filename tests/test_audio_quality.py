"""Quality selection, permissions, source ownership and actual-quality display."""
import json
from pathlib import Path
import time
import unittest

import gi
for api in ('4.1', '4.0'):
    try:
        gi.require_version('JavaScriptCore', api)
        break
    except ValueError:
        pass
from gi.repository import JavaScriptCore as JSC, GLib

FIXTURE = r'''
const location={origin:'https://music.163.com',pathname:'/st/webplayer'};
const intervals=[],timers=new Map();let timerId=0;
const setInterval=fn=>(intervals.push(fn),intervals.length),clearInterval=()=>{};
const setTimeout=(fn,delay)=>{timers.set(++timerId,{fn,delay});return timerId;};
const clearTimeout=id=>timers.delete(id),requestAnimationFrame=fn=>fn();
const window={addEventListener:()=>{}},innerWidth=1280,innerHeight=840;
const getComputedStyle=()=>({color:'rgb(40,40,40)',getPropertyValue:()=> 'rgb(40,40,40)'});
class Element{
 constructor(tag){this.tagName=tag;this.children=[];this.dataset={};this.style={setProperty(name,value){this[name]=value;}};this.attrs={};this.events={};this.textContent='';this.disabled=false;}
 appendChild(node){this.children.push(node);node.parentNode=this;return node;}
 insertBefore(node){this.children.unshift(node);node.parentNode=this;}
 setAttribute(name,value){this.attrs[name]=value;}
 getAttribute(name){return this.attrs[name];}
 addEventListener(name,fn){this.events[name]=fn;}
 contains(node){return node===this||this.children.some(c=>c.contains(node));}
 querySelectorAll(selector){const result=[];const visit=node=>{for(const child of node.children){
  const match=selector.startsWith('.')?(child.className||'').split(' ').includes(selector.slice(1)):
   selector.includes('aria-checked')?child.attrs['aria-checked']==='true'&&(!selector.includes(':disabled')||!child.disabled):
   selector.startsWith('button')?child.tagName==='button'&&(!selector.includes(':disabled')||!child.disabled):false;
  if(match)result.push(child);visit(child);
 }};visit(this);return result;}
 querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
 getBoundingClientRect(){return{top:760,bottom:800,left:1040,right:1100,width:60,height:40};}
 focus(){document.activeElement=this;}
 click(){if(!this.disabled&&this.events.click)this.events.click({target:this,stopPropagation(){}});}
 canPlayType(){return codecSupport?'probably':'';}
}
const document={head:new Element('head'),body:new Element('body'),activeElement:null,
 createElement:tag=>new Element(tag),addEventListener:()=>{},
 querySelectorAll:selector=>selector.startsWith('#page_pc_mini_bar')?[bar]:document.body.querySelectorAll(selector)};
const bar=new Element('div');document.body.appendChild(bar);
class MutationObserver{constructor(fn){this.callback=fn;}observe(){}disconnect(){}}
let state={host:{isPlusVip:true,isVinylVip:true,isAnonymous:false},configCenter:{},
 setting:{quantity:{listen:320,listenReg:320,listenAnon:192}},
 playing:{resourceTrackId:123,playId:1,resourcePlayingQuality:320,playingState:2,resourceType:'track',
 resourcePrivilege:{maxFreeBr:192},curPlaying:{track:{privilege:{maxSongBr:999000},available:[128,192,320,999,1999,3999,4999,5999]}}}};
const actions=[],subscribers=[],requests=[],detailRequests=[],nativeMessages=[];
const store={getState:()=>state,subscribe:fn=>(subscribers.push(fn),()=>{}),notify:()=>subscribers.forEach(fn=>fn()),
 dispatch:action=>{actions.push(action);
  if(action.type==='setting/updateQuantity')Object.assign(state.setting.quantity,action.payload);
  if(action.type==='playing/pause'){howl.paused=true;state.playing.playingState=1;}
  store.notify();return action;
 }};
const howl={_state:'loaded',paused:false,seek:()=>42.5,playing:()=>!howl.paused};
window.__musicNativeHowl=()=>howl;
const preparations=[],released=[];
class AbortController{constructor(){const listeners=new Set();this.signal={aborted:false,addEventListener:(_,fn)=>listeners.add(fn),removeEventListener:(_,fn)=>listeners.delete(fn)};this.listeners=listeners;}abort(){this.signal.aborted=true;for(const fn of this.listeners)fn();}}
const enablePreparation=()=>{window.__musicFetchNativeAudio=(url,signal,progress)=>new Promise((resolve,reject)=>preparations.push({url,signal,progress,resolve,reject}));};
const modules={},cache={};
function requireModule(id){if(cache[id])return cache[id].exports;const m=cache[id]={exports:{}};modules[id](m,m.exports,requireModule);return m.exports;}
requireModule.d=(exports,key,getter)=>Object.defineProperty(exports,key,{enumerable:true,get:getter});
const factories={
 tool:function(module,exports){exports.a={app:{_store:store},getStore(){return this.app._store.getState();},getDispatch(){return this.app._store.dispatch;}};},
 api:function(module,exports,require){const endpoint='/api/song/enhance/player/url/v1';let request;require.d(exports,'Of',()=>request);require('consumer');request=(params,options)=>new Promise((resolve,reject)=>requests.push({params,options,resolve,reject}));exports.Sf=params=>new Promise((resolve,reject)=>detailRequests.push({params,resolve,reject}));},
 consumer:function(module,exports,require){exports.api=require('api');},
 meta:function(module,exports){exports.b={4999:{serverUsedId:"jymaster"},5999:{serverUsedId:"sky"}};exports.d=track=>track.available;},
 maps:function(module,exports){exports.q=new Map([[5999e3,"sky"],[4999e3,"jymaster"]]);exports.p=new Map([['jymaster',4999000]]);exports.b={4999:'jymaster',5999:"sky"};},
 resolver:function(module,exports){exports.map=new Map([[5999e3,"sky"]]);exports.b=function(choice){return choice.quality===4999?"jymaster":"exhigh";};}
};
'''


class AudioQualityTests(unittest.TestCase):
    def setUp(self):
        self.create_context()

    def create_context(self, vivid=True, native=False):
        self.context = JSC.Context.new()
        self.evaluate('const codecSupport=' + ('true' if vivid else 'false') + ';')
        self.evaluate(FIXTURE)
        if native:
            self.evaluate('window.webkit={messageHandlers:{musicQuality:{postMessage:value=>nativeMessages.push(JSON.parse(value))}}};')
        source = (Path(__file__).resolve().parents[1] / 'assets/audio-quality.js').read_text()
        # Test-only access to the controller; the distributed script keeps it private.
        source = source.rsplit('})();', 1)[0] + '\nwindow.qualityTest={find,choose,availability,sync,place};\n})();'
        self.evaluate(source)
        self.evaluate('''
const oldPush=window.webpackJsonp.push.bind(window.webpackJsonp);
window.webpackJsonp.push=function(chunk){Object.assign(modules,chunk[1]);oldPush(chunk);};
window.webpackJsonp.push([[],factories]);
for(const id of Object.keys(factories))requireModule(id);
intervals[0]();
const select=level=>window.qualityTest.choose(window.qualityTest.find(level));
''')

    def evaluate(self, source):
        result = self.context.evaluate(source, -1)
        error = self.context.get_exception()
        self.assertIsNone(error, error.get_message() if error else '')
        return result

    def snapshot(self, source=''):
        self.evaluate(source)
        deadline = time.monotonic() + .02
        while time.monotonic() < deadline:
            while GLib.MainContext.default().pending():
                GLib.MainContext.default().iteration(False)
            time.sleep(.001)
        return json.loads(self.evaluate('''JSON.stringify({actions,nativeMessages,released,preparations:preparations.map(p=>({aborted:p.signal.aborted})),requests:requests.map(r=>r.params),
 preference:state.setting.quantity.listenReg,
 button:document.body.querySelector('.ncm-quality-button').textContent,
 footer:document.body.querySelector('.ncm-quality-footer').textContent,
 rows:document.body.querySelectorAll('.ncm-quality-row').map(r=>({level:r.dataset.level,disabled:r.disabled,checked:r.getAttribute('aria-checked')}))})''').to_string())

    def complete(self, level, **extra):
        data = dict(id=123, url='https://m10.music.126.net/music.flac', level=level, br=1234000, **extra)
        return self.snapshot('requests[0].resolve({code:200,data:[%s]});' % json.dumps(data))

    def test_bootstrap_replacement_keeps_one_button_and_nine_choices(self):
        result = self.snapshot('window.qualityTest.place();window.qualityTest.place();')
        self.assertEqual(len(result['rows']), 9)
        self.assertEqual(self.evaluate("document.body.querySelectorAll('.ncm-quality-button').length").to_int32(), 1)

    def test_vivid_extends_request_and_response_mapping(self):
        self.assertEqual(self.evaluate("requireModule('maps').q.get(6999000)").to_string(), 'vivid')
        self.assertEqual(self.evaluate("requireModule('maps').p.get('vivid')").to_int32(), 6999000)
        self.assertEqual(self.evaluate("requireModule('resolver').b({quality:6999})").to_string(), 'vivid')
        self.assertEqual(self.evaluate("requireModule('meta').b[6999].serverUsedId").to_string(), 'vivid')
        self.assertEqual(self.evaluate("requireModule('resolver').b({quality:4999})").to_string(), 'jymaster')

    def test_official_detail_enables_master_even_when_legacy_flags_are_missing(self):
        self.snapshot('state.playing.curPlaying.track.available=[128,192,320];document.body.querySelector(".ncm-quality-button").click();')
        result = self.snapshot('detailRequests[0].resolve({data:{l:{size:1},m:{size:1},h:{size:1},jm:{size:166000000},vi:{size:27000000}}});')
        self.assertFalse(next(r for r in result['rows'] if r['level']=='jymaster')['disabled'])
        self.assertFalse(next(r for r in result['rows'] if r['level']=='vivid')['disabled'])
        self.assertTrue(next(r for r in result['rows'] if r['level']=='lossless')['disabled'])

    def test_reopening_menu_reuses_song_detail(self):
        self.snapshot('document.body.querySelector(".ncm-quality-button").click();')
        self.snapshot('detailRequests[0].resolve({data:{h:{size:1}}});')
        self.snapshot('document.body.querySelector(".ncm-quality-button").click();document.body.querySelector(".ncm-quality-button").click();')
        self.assertEqual(self.evaluate('detailRequests.length').to_int32(),1)

    def test_normal_vip_cannot_select_svip_levels(self):
        result = self.snapshot('state.host.isPlusVip=false;store.notify();select("vivid");')
        unavailable = {r['level'] for r in result['rows'] if r['disabled']}
        self.assertTrue({'vivid', 'sky', 'jymaster'} <= unavailable)
        self.assertNotIn('lossless', unavailable)
        self.assertEqual(result['requests'], [])

    def test_anonymous_keeps_free_levels_available(self):
        result = self.snapshot('state.host={isAnonymous:true};store.notify();')
        self.assertEqual({r['level'] for r in result['rows'] if not r['disabled']}, {'standard', 'higher'})

    def test_missing_song_quality_is_disabled(self):
        result = self.snapshot('state.playing.curPlaying.track.available=[128,192,320];store.notify();')
        self.assertTrue(next(r for r in result['rows'] if r['level']=='lossless')['disabled'])

    def test_lossless_request_uses_flac_and_keeps_current_position(self):
        result = self.snapshot('select("lossless");')
        self.assertEqual(result['requests'][0]['encodeType'], 'flac')
        result = self.complete('lossless')
        switch = next(a for a in result['actions'] if a['type']=='playing/switchQuality')
        self.assertEqual(switch['payload']['current'], 42.5)
        self.assertEqual(switch['payload']['quality']['quality'], 999)

    def test_quality_copy_is_prepared_while_old_audio_keeps_playing(self):
        self.snapshot('enablePreparation();select("lossless");')
        result = self.complete('lossless')
        self.assertEqual(result['actions'], [])
        self.assertEqual(result['preference'],320)
        self.assertTrue(self.evaluate('howl.playing()').to_boolean())
        result = self.snapshot('preparations[0].resolve({release:()=>released.push(1)});')
        self.assertEqual(result['actions'][-1]['type'],'playing/switchQuality')
        self.assertEqual(result['released'],[])
        result = self.snapshot('state.playing.resourcePlayingQuality=999;store.notify();')
        self.assertEqual(result['released'],[1])

    def test_prepared_reply_is_reused_only_for_the_matching_song_and_level(self):
        self.snapshot('enablePreparation();select("lossless");')
        self.complete('lossless')
        self.snapshot('preparations[0].resolve({release:()=>released.push(1)});')
        result = self.snapshot("requireModule('consumer').api.Of({ids:['[123]'],level:'lossless'});")
        self.assertEqual(len(result['requests']),1)
        result = self.snapshot("requireModule('consumer').api.Of({ids:['[456]'],level:'lossless'});")
        self.assertEqual(len(result['requests']),2)

    def test_changing_track_cancels_preparation_and_ignores_late_result(self):
        self.snapshot('enablePreparation();select("lossless");')
        self.complete('lossless')
        result = self.snapshot('state.playing.resourceTrackId=456;store.notify();preparations[0].resolve({release:()=>released.push(1)});')
        self.assertTrue(result['preparations'][0]['aborted'])
        self.assertEqual(result['actions'],[])
        self.assertEqual(result['released'],[1])

    def test_track_change_during_switch_discards_the_old_seek_position(self):
        self.snapshot('select("lossless");')
        self.complete('lossless')
        result = self.snapshot('state.playing.resourceTrackId=456;store.notify();')
        self.assertEqual(result['actions'][-1],{'type':'playing/onLoadingSeekUpdate','payload':{'loadingSeekDuration':0}})

    def test_circular_imports_share_the_same_quality_request(self):
        self.assertTrue(self.evaluate("requireModule('consumer').api.Of===requireModule('api').Of").to_boolean())
        result = self.snapshot("requireModule('consumer').api.Of({ids:['123'],level:'jymaster',encodeType:'mp3'});")
        self.assertEqual(result['requests'][0]['encodeType'], 'flac')

    def test_native_bridge_accepts_the_websites_encoded_id_array(self):
        self.create_context(native=True)
        result = self.snapshot("requireModule('consumer').api.Of({ids:['[123]'],level:'jymaster'});")
        self.assertEqual(result['nativeMessages'][0]['params']['ids'], [123])
        self.assertEqual(result['requests'], [])

    def test_native_bridge_accepts_multiple_ids_as_json(self):
        self.create_context(native=True)
        result = self.snapshot("requireModule('api').Of({ids:'[123,456]',level:'exhigh'});")
        self.assertEqual(result['nativeMessages'][0]['params']['ids'], [123,456])

    def test_track_change_cancels_native_quality_preflight(self):
        self.create_context(native=True)
        result = self.snapshot('select("lossless");state.playing.resourceTrackId=456;store.notify();')
        self.assertEqual([message['event'] for message in result['nativeMessages']], ['request','cancel'])
        self.assertEqual(result['nativeMessages'][0]['id'],result['nativeMessages'][1]['id'])

    def test_vivid_uses_its_own_level_and_mp3_encoding(self):
        result = self.snapshot('select("vivid");')
        self.assertEqual(result['requests'][0]['level'], 'vivid')
        self.assertEqual(result['requests'][0]['encodeType'], 'mp3')
        result = self.complete('vivid')
        switch = next(a for a in result['actions'] if a['type']=='playing/switchQuality')
        self.assertEqual(switch['payload']['quality'], {'quality':6999, 'type':'envSound'})

    def test_missing_av3a_decoder_disables_vivid_before_playback_changes(self):
        self.create_context(vivid=False)
        result = self.snapshot('select("vivid");')
        self.assertTrue(next(row for row in result['rows'] if row['level']=='vivid')['disabled'])
        self.assertEqual(result['requests'], [])
        self.assertEqual(result['actions'], [])

    def test_failed_preflight_leaves_playback_and_preference_untouched(self):
        self.snapshot('select("lossless");')
        result = self.snapshot('requests[0].reject(new Error("network"));')
        self.assertEqual(result['actions'], [])
        self.assertEqual(result['preference'], 320)
        self.assertEqual(result['button'], '极高')

    def test_trial_response_does_not_replace_the_complete_current_song(self):
        self.snapshot('select("lossless");')
        result = self.complete('lossless', freeTrialInfo={'start':0,'end':30})
        self.assertEqual(result['actions'], [])

    def test_track_change_cancels_late_quality_result(self):
        self.snapshot('select("lossless");state.playing.resourceTrackId=456;store.notify();')
        result = self.complete('lossless')
        self.assertEqual(result['actions'], [])

    def test_server_fallback_displays_actual_quality_and_remembers_preference(self):
        self.snapshot('select("jymaster");')
        result = self.complete('exhigh')
        self.assertEqual(result['preference'], 4999)
        self.assertEqual(result['button'], '极高')
        self.assertEqual([a['type'] for a in result['actions']], ['setting/updateQuantity'])

    def test_paused_song_stays_paused_after_quality_change(self):
        self.snapshot('howl.paused=true;state.playing.playingState=1;select("lossless");')
        self.complete('lossless')
        result = self.snapshot('howl.paused=false;state.playing.playId=2;state.playing.resourcePlayingQuality=999;store.notify();')
        self.assertEqual(result['actions'][-1]['type'], 'playing/pause')
        self.assertEqual(result['button'], '无损')

    def test_reused_play_id_still_completes_and_preserves_pause(self):
        self.snapshot('howl.paused=true;state.playing.playingState=1;select("lossless");')
        self.complete('lossless')
        result = self.snapshot('howl.paused=false;state.playing.resourcePlayingQuality=999;store.notify();')
        self.assertEqual(result['actions'][-1]['type'], 'playing/pause')
        self.assertEqual(result['button'], '无损')
        self.assertTrue(all(not row['disabled'] for row in result['rows']))

    def test_track_change_clears_previous_switch_notice(self):
        self.snapshot('select("jymaster");')
        self.complete('exhigh')
        result = self.snapshot('state.playing.resourceTrackId=456;store.notify();')
        self.assertNotIn('已保存偏好', result['footer'])

    def test_repeated_click_does_not_start_competing_switches(self):
        result = self.snapshot('select("lossless");select("hires");')
        self.assertEqual(len(result['requests']), 1)

    def test_loading_song_is_left_undisturbed(self):
        result = self.snapshot('howl._state="loading";select("lossless");')
        self.assertEqual(result['requests'], [])
        self.assertEqual(result['actions'], [])

    def test_empty_queue_saves_preference_without_loading_audio(self):
        result = self.snapshot('state.playing.resourceTrackId=0;select("lossless");')
        self.assertEqual(result['requests'], [])
        self.assertEqual(result['preference'], 999)
