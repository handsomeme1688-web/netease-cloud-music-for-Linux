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
const listeners=new Map(),documentListeners=new Map(),observers=[];
const window={
 addEventListener(name,fn){listeners.set(name,[...(listeners.get(name)||[]),fn]);},
 dispatchEvent(event){for(const listener of listeners.get(event.type)||[])listener(event);}
},innerWidth=1280,innerHeight=840;
class CustomEvent{constructor(type,{detail}){this.type=type;this.detail=detail;}}
const getComputedStyle=()=>({color:'rgb(40,40,40)',getPropertyValue:()=> 'rgb(40,40,40)'});
class Element{
 constructor(tag){this.tagName=tag;this.children=[];this.dataset={};this.style={setProperty(name,value){this[name]=value;}};this.attrs={};this.events={};this.textContent='';this.disabled=false;}
 insertBefore(node,before){
  if(node.parentNode)node.parentNode.children.splice(node.parentNode.children.indexOf(node),1);
  this.children.splice(before?this.children.indexOf(before):this.children.length,0,node);
  node.parentNode=this;return node;
 }
 appendChild(node){return this.insertBefore(node,null);}
 get firstChild(){return this.children[0]||null;}
 closest(selector){for(let node=this;node;node=node.parentNode){
  if((node.className||'').split(' ').includes(selector.slice(1)))return node;
 }return null;}
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
 getBoundingClientRect(){return this.bounds||{top:760,bottom:800,left:1040,right:1100,width:60,height:40};}
 focus(){document.activeElement=this;}
 click(){if(!this.disabled&&this.events.click)this.events.click({target:this,stopPropagation(){}});}
 canPlayType(){return codecSupport?'probably':'';}
}
const document={head:new Element('head'),body:new Element('body'),activeElement:null,
 createElement:tag=>new Element(tag),addEventListener:(type,fn)=>documentListeners.set(type,fn),
 querySelector:selector=>selector==='#page_pc_setting #play > .play'?settings:document.body.querySelector(selector),
 querySelectorAll:selector=>selector.startsWith('#page_pc_mini_bar')?(detailVisible?[bar,detailBar]:[bar]):document.body.querySelectorAll(selector)};
const bar=new Element('div');document.body.appendChild(bar);
const settings=new Element('div');document.body.appendChild(settings);
const detailBar=new Element('div');detailBar.className='vinyl-page-bar-wrapper';
document.body.appendChild(detailBar);
let detailVisible=false;
class MutationObserver{constructor(fn){this.callback=fn;}observe(_,options){this.options=options;observers.push(this);}disconnect(){}}
let state={host:{isPlusVip:true,isVinylVip:true,isAnonymous:false},configCenter:{},
 setting:{quantity:{listen:320,listenReg:320,listenAnon:192}},
 playing:{resourceTrackId:123,playId:1,resourcePlayingQuality:320,playingState:2,resourceType:'track',
 resourcePrivilege:{maxFreeBr:192},curPlaying:{track:{privilege:{maxSongBr:999000},available:[128,192,320,999,1999,3999,4999,5999]}}}};
const actions=[],subscribers=[],requests=[],detailRequests=[],nativeMessages=[];
const store={getState:()=>state,subscribe:fn=>(subscribers.push(fn),()=>{}),notify:()=>subscribers.forEach(fn=>fn()),
 dispatch:action=>{actions.push(action);
  if(action.type==='setting/updateQuantity')Object.assign(state.setting.quantity,action.payload);
  if(action.type==='playing/onLoadingSeekUpdate')Object.assign(state.playing,action.payload);
  if(action.type==='playing/pause'){howl.paused=true;state.playing.playingState=1;}
  store.notify();return action;
 }};
const loadCallbacks=[];
const howl={_state:'loaded',paused:false,seek:()=>42.5,playing:()=>!howl.paused,
 once:(event,callback)=>{if(event==='load')loadCallbacks.push(callback);}};
window.__musicNativeHowl=()=>howl;
const preparations=[],released=[];
class AbortController{constructor(){const listeners=new Set();this.signal={aborted:false,addEventListener:(_,fn)=>listeners.add(fn),removeEventListener:(_,fn)=>listeners.delete(fn)};this.listeners=listeners;}abort(){this.signal.aborted=true;for(const fn of this.listeners)fn();}}
const enablePreparation=()=>{window.__musicFetchNativeAudio=(url,signal,progress,background)=>new Promise((resolve,reject)=>preparations.push({url,signal,progress,background,resolve,reject}));};
const modules={},cache={};
function requireModule(id){if(cache[id])return cache[id].exports;const m=cache[id]={exports:{}};modules[id](m,m.exports,requireModule);return m.exports;}
requireModule.d=(exports,key,getter)=>Object.defineProperty(exports,key,{enumerable:true,get:getter});
const factories={
 tool:function(module,exports){exports.a={app:{_store:store},getStore(){return this.app._store.getState();},getDispatch(){return this.app._store.dispatch;}};},
 api:function(module,exports,require){const endpoint='/api/song/enhance/player/url/v1';let request;require.d(exports,'Of',()=>request);require('consumer');request=(params,options)=>new Promise((resolve,reject)=>requests.push({params,options,resolve,reject}));exports.Sf=params=>new Promise((resolve,reject)=>detailRequests.push({params,resolve,reject}));},
 consumer:function(module,exports,require){exports.api=require('api');},
 meta:function(module,exports){exports.b={4999:{serverUsedId:"jymaster"},5999:{serverUsedId:"sky"}};exports.d=track=>track.available;},
 maps:function(module,exports){exports.q=new Map([[5999e3,"sky"],[4999e3,"jymaster"]]);exports.p=new Map([['jymaster',4999000]]);exports.b={4999:'jymaster',5999:"sky"};},
 bridge:function(module,exports){exports.AudioPlayer={getCacheProgressPercent(){return 1;},preLoad(){return this.getCacheProgressPercent();}};},
 progress:function(module,exports){
  const subject=value=>{
   const listeners=[];
   return {getValue:()=>value,next:next=>{value=next;listeners.forEach(fn=>fn(next));},
    subscribe:fn=>listeners.push(fn),asObservable(){return this;}};
  };
  exports.b=subject(false);exports.c=subject({inSeek:!1});exports.d=subject(null);
  exports.d.asObservable();
 },
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
        source = source.rsplit('})();', 1)[0] + '\nwindow.qualityTest={find,choose,sync,place};\n})();'
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
 button:document.body.querySelector('.ncm-quality-mini').textContent,
 settings:settings.querySelectorAll('.ncm-quality-setting-radio').find(input=>input.checked)?.parentNode.children[1].textContent,
 detail:document.body.querySelector('.ncm-quality-detail').textContent,
 footer:document.body.querySelector('.ncm-quality-footer').textContent,
 rows:document.body.querySelectorAll('.ncm-quality-row').map(r=>({level:r.dataset.level,disabled:r.disabled,checked:r.getAttribute('aria-checked')}))})''').to_string())

    def complete(self, level, **extra):
        data = dict(id=123, url='https://m10.music.126.net/music.flac', level=level, br=1234000, **extra)
        return self.snapshot('requests[0].resolve({code:200,data:[%s]});' % json.dumps(data))

    def test_desktop_lyrics_cancels_the_previous_song_on_track_change(self):
        self.evaluate('''
const lyricMessages=[], lyricRequests=[];
window.webkit={messageHandlers:{desktopLyrics:{postMessage:value=>lyricMessages.push(JSON.parse(value))}}};
const fetch=(url,{signal})=>new Promise(resolve=>lyricRequests.push({url,signal,resolve}));
const respond=(index,text)=>lyricRequests[index].resolve({ok:true,
    json:async()=>({code:200,lrc:{lyric:text}})});
const progress=requireModule('progress').d;
delete progress.getValue;
progress.next({playId:'123|play|token',current:41.5});
let updates=0;
store.subscribe(()=>updates++);
''')
        self.evaluate((Path(__file__).resolve().parents[1] / 'assets/desktop-lyrics.js').read_text())
        self.assertEqual(self.evaluate("lyricRequests.length").to_int32(), 0)
        self.snapshot('window.__musicDesktopLyrics.setVisible(true);')
        self.assertAlmostEqual(self.evaluate("lyricMessages.find(m=>m.event==='position').position").to_double(), 41.5)
        self.snapshot('state.playing.resourceTrackId=456;store.notify();')
        self.assertEqual(self.evaluate('updates').to_int32(), 1)
        self.assertTrue(self.evaluate('lyricRequests[0].signal.aborted').to_boolean())
        self.snapshot('respond(0,"[00:02]Old");respond(1,"[00:03]New");')
        messages = json.loads(self.evaluate("JSON.stringify(lyricMessages.filter(m=>m.event==='lyrics'))").to_string())
        self.assertEqual([(m['id'], m['lrc']) for m in messages], [('456', '[00:03]New')])
        self.snapshot('window.__musicDesktopLyrics.setVisible(false);state.playing.resourceTrackId=789;store.notify();')
        self.assertEqual(self.evaluate("lyricRequests.length").to_int32(), 2)
        self.snapshot('state.playing.resourceTrackId=null;window.__musicDesktopLyrics.setVisible(true);')
        self.assertEqual(self.evaluate("lyricMessages.slice(-1)[0].event").to_string(), "track")
        self.assertEqual(self.evaluate("lyricMessages.slice(-1)[0].id").to_string(), "")

    def test_settings_show_nine_choices_and_playback_buttons_share_one_menu(self):
        result = self.snapshot('window.qualityTest.place();window.qualityTest.place();')
        self.assertEqual(len(result['rows']), 9)
        self.assertEqual(self.evaluate("document.body.querySelectorAll('.ncm-quality-button').length").to_int32(), 2)
        self.assertEqual(self.evaluate("settings.querySelectorAll('.ncm-quality-setting-radio').length").to_int32(), 9)
        self.assertEqual(self.evaluate("settings.querySelectorAll('.ncm-quality-setting-radio').filter(input=>input.checked).length").to_int32(), 1)

    def test_both_bars_have_quality_ready_before_detail_animation(self):
        self.evaluate('''
const miniButton=document.body.querySelector('.ncm-quality-mini');
const detailButton=document.body.querySelector('.ncm-quality-detail');
const observer=observers.find(item=>item.options.attributeFilter?.includes('class'));
bar.isConnected=true;
detailBar.nodeType=1;
detailBar.matches=()=>true;
detailBar.isConnected=true;
detailBar.bounds={...detailBar.getBoundingClientRect(),top:845,bottom:885};
detailVisible=true;
observer.callback([{type:'childList',target:document.body,addedNodes:[detailBar]}]);
''')
        self.assertTrue(self.evaluate(
            '!miniButton.hidden && !detailButton.hidden && miniButton.parentNode===bar && detailButton.parentNode===detailBar'
        ).to_boolean())
        self.evaluate('''
documentListeners.get('transitionend')({target:detailBar});
''')
        self.assertTrue(self.evaluate('!miniButton.hidden && !detailButton.hidden').to_boolean())
        self.evaluate('''
detailVisible=false;
detailBar.isConnected=false;
observer.callback([{type:'childList',target:document.body,addedNodes:[]}]);
''')
        self.assertTrue(self.evaluate('!miniButton.hidden && detailButton.hidden').to_boolean())

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
        self.assertFalse(next(r for r in result['rows'] if r['level']=='lossless')['disabled'])

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

    def test_missing_song_quality_can_be_saved_as_the_default(self):
        result = self.snapshot('state.playing.curPlaying.track.available=[128,192,320];store.notify();')
        self.assertFalse(next(r for r in result['rows'] if r['level']=='lossless')['disabled'])
        result = self.snapshot('select("lossless");')
        self.assertEqual(result['settings'], '无损')
        self.assertEqual(result['requests'][0]['level'], 'lossless')

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
        self.assertEqual([a['type'] for a in result['actions']], ['setting/updateQuantity'])
        self.assertEqual(result['preference'],999)
        self.assertTrue(self.evaluate('howl.playing()').to_boolean())
        result = self.snapshot('preparations[0].resolve({release:()=>released.push(1)});')
        self.assertEqual(result['actions'][-1]['type'],'playing/switchQuality')
        self.assertEqual(result['released'],[])
        result = self.snapshot('state.playing.resourcePlayingQuality=999;store.notify();')
        self.assertEqual(result['released'],[1])

    def test_streaming_quality_switch_resumes_at_current_position_before_completion(self):
        self.evaluate('''
const messages=[];
window.webkit={messageHandlers:{streamPlayer:{postMessage:value=>messages.push(JSON.parse(value))}}};
''')
        self.evaluate((Path(__file__).resolve().parents[1] / 'assets/native-streaming.js').read_text())
        self.snapshot('enablePreparation();select("lossless");')
        self.snapshot('''
const url='https://m10.music.126.net/file-without-extension';
requests[0].resolve({code:200,data:[{id:123,url,level:'lossless',type:'flac',time:120000}]});
''')
        result = self.snapshot('preparations[0].progress(300000,1200000);')
        self.assertEqual([action['type'] for action in result['actions']], ['setting/updateQuantity'])
        self.assertTrue(self.evaluate('howl.playing()').to_boolean())
        result = self.snapshot('howl.seek=()=>45;preparations[0].progress(470000,1200000);')
        self.assertEqual(len(result['actions']), 1)
        result = self.snapshot('preparations[0].progress(490000,1200000);')
        self.assertEqual(result['actions'][-1]['type'], 'playing/switchQuality')
        self.assertEqual(result['actions'][-1]['payload']['current'], 45)
        self.assertFalse(result['preparations'][0]['aborted'])
        self.evaluate("window.__musicStreamingHowl({}, {autoplay:true}, url);")
        self.assertEqual(self.evaluate("messages.find(m=>m.event==='load').position").to_int32(), 45)
        result = self.snapshot('state.playing.resourcePlayingQuality=999;store.notify();')
        self.assertTrue(result['preparations'][0]['aborted'])

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
        self.assertEqual([a['type'] for a in result['actions']], ['setting/updateQuantity'])
        self.assertEqual(result['released'],[1])

    def test_track_change_during_switch_discards_the_old_seek_position(self):
        self.snapshot('select("lossless");')
        self.complete('lossless')
        result = self.snapshot('state.playing.resourceTrackId=456;store.notify();')
        self.assertEqual(result['actions'][-1],{'type':'playing/onLoadingSeekUpdate','payload':{'loadingSeekDuration':0}})

    def test_pending_seek_stays_with_its_own_song(self):
        self.snapshot('state.playing.loadingSeekDuration=96;store.notify();')
        self.assertEqual(self.evaluate('state.playing.loadingSeekDuration').to_int32(), 96)
        self.snapshot('state.playing.resourceTrackId=456;store.notify();')
        self.assertEqual(self.evaluate('state.playing.loadingSeekDuration').to_int32(), 0)
        self.snapshot('''
state.playing.resourceTrackId=789;
state.playing.restoreResource={trackId:789};
state.playing.loadingSeekDuration=31;
store.notify();
''')
        self.assertEqual(self.evaluate('state.playing.loadingSeekDuration').to_int32(), 31)

    def test_native_clock_unfreezes_the_next_song_and_ignores_stale_ticks(self):
        self.evaluate('''
const messages=[];
window.webkit={messageHandlers:{streamPlayer:{postMessage:message=>messages.push(JSON.parse(message))}}};
window.__musicNativeHowl=()=>window.__musicStreamingActive();
''')
        path = Path(__file__).resolve().parents[1] / 'assets/native-streaming.js'
        self.evaluate(path.read_text())
        self.evaluate('''
const channel=requireModule('progress');
const send=(id,event,position,buffering=false)=>window.__musicStreamEvent(
 id,event,{position,duration:120,bytes:1,total:2,playing:true,buffering});
const oldSong={};
window.__musicStreamingHowl(oldSong,{autoplay:true},'https://m10.music.126.net/old.mp3');
const oldId=messages[0].id;
send(oldId,'load',0);
send(oldId,'tick',9);
channel.b.next(true);
send(oldId,'tick',9,true);
state.playing.resourceTrackId=456;
state.playing.playId='123_stalled';
store.notify();
send(oldId,'tick',10);
''')
        self.assertTrue(self.evaluate('channel.b.getValue()').to_boolean())
        self.assertEqual(self.evaluate('channel.d.getValue().current').to_int32(), 9)
        self.evaluate('''
oldSong.unload();
const nextSong={};
window.__musicStreamingHowl(nextSong,{autoplay:true},'https://m10.music.126.net/next.mp3');
const nextId=messages.find(message=>message.url?.endsWith('next.mp3')).id;
send(nextId,'load',0);
send(oldId,'tick',85);
send(nextId,'tick',1.6);
''')
        self.assertFalse(self.evaluate('channel.b.getValue()').to_boolean())
        self.assertEqual(self.evaluate('channel.d.getValue().playId').to_string(), '456')
        self.assertAlmostEqual(self.evaluate('channel.d.getValue().current').to_double(), 1.6)
        self.evaluate('''
channel.c.next({inSeek:true});
channel.b.next(true);
send(nextId,'tick',2.1);
channel.c.next({inSeek:false});
send(nextId,'tick',2.1,true);
''')
        self.assertTrue(self.evaluate('channel.b.getValue()').to_boolean())
        self.assertAlmostEqual(self.evaluate('channel.d.getValue().current').to_double(), 1.6)
        self.evaluate("send(nextId,'tick',2.4);")
        self.assertAlmostEqual(self.evaluate('channel.d.getValue().current').to_double(), 2.4)

    def test_circular_imports_share_the_same_quality_request(self):
        self.assertTrue(self.evaluate("requireModule('consumer').api.Of===requireModule('api').Of").to_boolean())
        result = self.snapshot("requireModule('consumer').api.Of({ids:['123'],level:'jymaster',encodeType:'mp3'});")
        self.assertEqual(result['requests'][0]['encodeType'], 'flac')

    def test_preload_is_reused_after_the_server_refreshes_the_audio_url(self):
        self.snapshot('''
const md5 = 'a'.repeat(32);
enablePreparation();
requireModule('bridge').AudioPlayer.preLoad({musicurl:'http://m10.music.126.net/song.flac?old', md5, fileSize:200});
requireModule('api').Of({ids:['123'],level:'jymaster'});
''')
        result = self.snapshot('''
requests[0].resolve({data:[{id:123,level:'jymaster',url:'https://m10.music.126.net/song.flac?new',md5,size:200}]});
''')
        self.assertEqual(len(result['preparations']), 1)
        result = self.snapshot('''
const signal = new AbortController().signal;
window.__musicTakePreload('https://m10.music.126.net/song.flac?new',signal,()=>{}).then(copy=>copy.release());
preparations[0].resolve({release:()=>released.push(1)});
''')
        self.assertEqual(result['released'], [1])
        self.assertFalse(result['preparations'][0]['aborted'])

    def test_unrelated_playback_discards_preload_and_its_late_result(self):
        result = self.snapshot('''
enablePreparation();
requireModule('bridge').AudioPlayer.preLoad({musicurl:'https://m10.music.126.net/next.flac'});
window.__musicTakePreload('https://m10.music.126.net/different.flac',new AbortController().signal,()=>{});
preparations[0].resolve({release:()=>released.push(1)});
''')
        self.assertTrue(result['preparations'][0]['aborted'])
        self.assertEqual(result['released'], [1])

    def test_transition_prepares_before_download_finishes_and_checks_the_next_song(self):
        self.snapshot('''
enablePreparation();
state.playing.playingMode='playOrder';
state.playing.curPlaying.resourceId='current';
state.playingList={curPlayingList:[
 {resourceId:'current',displayOrder:1},{resourceId:'next',displayOrder:2}
]};
const transitions=[];
window.__musicPrepareTransition=(audio,url,duration,valid)=>transitions.push({audio,url,duration,valid});
requireModule('bridge').AudioPlayer.preLoad({songId:'next',songDuration:'210000',musicurl:'https://m10.music.126.net/next.flac'});
''')
        self.assertTrue(self.evaluate('transitions.length===1 && transitions[0].duration===210').to_boolean())
        self.assertTrue(self.evaluate('''
state.playingList.curPlayingList=state.playingList.curPlayingList.map(entry=>({...entry}));
transitions[0].valid()
''').to_boolean())
        self.assertFalse(self.evaluate('state.playingList.curPlayingList=[]; transitions[0].valid()').to_boolean())

    def test_confirmed_mix_reuses_the_authorized_next_song_url(self):
        self.create_context(native=True)
        self.snapshot('''
enablePreparation();
state.playing.playingMode='playCycle';
state.playing.curPlaying.resourceId='123';
state.playingList={curPlayingList:[
 {resourceId:'123',displayOrder:1},{resourceId:'456',displayOrder:2}
]};
const source='https://m10.music.126.net/next.flac';
const query=()=>requireModule('api').Of({ids:['456'],level:'lossless'});
query();
window.__musicQualityResponse(nativeMessages[0].id,{code:200,data:[
 {id:456,code:200,url:source,expi:1200,level:'lossless'}
]});
''')
        result = self.snapshot('''
window.__musicPrepareTransition=(audio,url,duration,valid)=>valid();
requireModule('bridge').AudioPlayer.preLoad({songId:456,songDuration:210000,musicurl:source});
let mixedSource;
query().then(response=>{mixedSource=response.data[0].url;});
''')
        self.assertEqual(len(result['nativeMessages']), 1)
        self.assertEqual(self.evaluate('mixedSource').to_string(), 'https://m10.music.126.net/next.flac')

    def test_prefetches_three_songs_in_sequence_and_yields_when_the_song_changes(self):
        self.snapshot('''
enablePreparation();
state.playing.playingMode='playOrder';
state.playingList={curPlayingList:[123,456,789,101,102].map((id,displayOrder)=>({resourceId:id,displayOrder}))};
requireModule('bridge').AudioPlayer.preLoad({songId:456,musicurl:'https://m10.music.126.net/456.mp3'});
preparations[0].resolve({persisted:true,release:()=>{}});
''')
        self.assertEqual(self.evaluate("requests[0].params.ids.join(',')").to_string(), '789,101')
        self.snapshot('''
requests[0].resolve({code:200,data:[789,101].map(id=>({
 id,code:200,url:'https://m10.music.126.net/'+id+'.mp3',type:'mp3'
}))});
''')
        self.assertTrue(self.evaluate("preparations.length===2 && preparations[1].background").to_boolean())
        self.snapshot('preparations[1].resolve({persisted:true,release:()=>released.push(789)});')
        self.assertTrue(self.evaluate("preparations.length===3 && preparations[2].url.endsWith('/101.mp3')").to_boolean())
        result = self.snapshot("window.__musicDiscardPreload('https://m10.music.126.net/other.mp3');")
        self.assertTrue(result['preparations'][2]['aborted'])
        self.assertEqual(result['released'], [789])

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

    def test_failed_native_lookup_uses_the_original_web_request(self):
        self.create_context(native=True)
        result = self.snapshot('''
const params={ids:['123'],level:'lossless'};
requireModule('api').Of(params);
window.__musicQualityResponse(nativeMessages[0].id,null);
requireModule('api').Of(params);
window.__musicQualityResponse(nativeMessages[1].id,{code:200,data:[{id:123,url:null}]});
''')
        self.assertEqual(result['requests'], [dict(ids=['123'], level='lossless', encodeType='flac')] * 2)

    def test_new_stream_releases_only_unrelated_preloads_before_loading(self):
        result = self.snapshot('''
enablePreparation();
requireModule('bridge').AudioPlayer.preLoad({musicurl:'https://m10.music.126.net/next.flac'});
window.__musicDiscardPreload('http://m10.music.126.net/next.flac');
''')
        self.assertFalse(result['preparations'][0]['aborted'])
        result = self.snapshot("window.__musicDiscardPreload('https://m10.music.126.net/other.flac');")
        self.assertTrue(result['preparations'][0]['aborted'])
        self.assertEqual(result['actions'], [])

    def test_failed_preflight_preserves_current_audio_and_saves_default(self):
        self.snapshot('select("lossless");')
        result = self.snapshot('requests[0].reject(new Error("network"));')
        self.assertEqual([a['type'] for a in result['actions']], ['setting/updateQuantity'])
        self.assertEqual(result['preference'], 999)
        self.assertEqual(result['button'], '极高')

    def test_trial_response_does_not_replace_the_complete_current_song(self):
        self.snapshot('select("lossless");')
        result = self.complete('lossless', freeTrialInfo={'start':0,'end':30})
        self.assertEqual([a['type'] for a in result['actions']], ['setting/updateQuantity'])

    def test_track_change_cancels_late_quality_result(self):
        self.snapshot('select("lossless");state.playing.resourceTrackId=456;store.notify();')
        result = self.complete('lossless')
        self.assertEqual([a['type'] for a in result['actions']], ['setting/updateQuantity'])

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
        self.assertNotIn('当前歌曲使用', result['footer'])

    def test_repeated_click_does_not_start_competing_switches(self):
        result = self.snapshot('select("lossless");select("hires");')
        self.assertEqual(len(result['requests']), 1)

    def test_loading_song_defers_switch_but_saves_default_immediately(self):
        result = self.snapshot('howl._state="loading";select("lossless");')
        self.assertEqual(result['requests'], [])
        self.assertEqual(result['preference'], 999)
        result = self.snapshot('''
howl._state='loaded';loadCallbacks.forEach(callback=>callback());
for(const timer of [...timers.values()])if(timer.delay===0)timer.fn();
''')
        self.assertEqual(result['requests'][0]['level'], 'lossless')

    def test_settings_and_both_playback_buttons_share_one_selection(self):
        result = self.snapshot('''
const radio=settings.querySelectorAll('.ncm-quality-setting-radio').find(input=>input.value==='999');
radio.checked=true;
radio.events.change();
''')
        self.assertEqual(result['settings'], '无损')
        self.assertEqual(result['requests'][0]['level'], 'lossless')
        self.assertTrue(next(r for r in result['rows'] if r['level']=='lossless')['checked']=='true')
        self.complete('lossless')
        result = self.snapshot('''
state.playing.resourcePlayingQuality=999;store.notify();
detailVisible=true;window.qualityTest.place();
document.body.querySelector('.ncm-quality-detail').click();
document.body.querySelectorAll('.ncm-quality-row').find(row=>row.dataset.level==='higher').click();
''')
        self.assertEqual(result['settings'], '较高')
        self.assertEqual(result['requests'][-1]['level'], 'higher')
        self.snapshot('requests[1].resolve({data:[{id:123,level:"higher",url:"https://m10.music.126.net/track.mp3"}]});')
        result = self.snapshot('''
state.playing.resourcePlayingQuality=192;store.notify();
detailVisible=false;window.qualityTest.place();
document.body.querySelector('.ncm-quality-mini').click();
document.body.querySelectorAll('.ncm-quality-row').find(row=>row.dataset.level==='standard').click();
''')
        self.assertEqual(result['settings'], '标准')
        self.assertEqual(result['requests'][-1]['level'], 'standard')
        self.assertTrue(self.evaluate("document.body.querySelector('.ncm-quality-detail').hidden").to_boolean())

    def test_empty_queue_saves_preference_without_loading_audio(self):
        result = self.snapshot('state.playing.resourceTrackId=0;select("lossless");')
        self.assertEqual(result['requests'], [])
        self.assertEqual(result['preference'], 999)
