"""Keep UI and desktop controls on the decoded audio clock."""
from pathlib import Path
import json,unittest
import gi
for api in ('4.1','4.0'):
    try:gi.require_version('JavaScriptCore',api);break
    except ValueError:pass
from gi.repository import JavaScriptCore as JSC
ROOT=Path(__file__).resolve().parents[1]/'assets'

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.context=JSC.Context.new()
        self.evaluate(r'''
const location={origin:'https://music.163.com',pathname:'/st/webplayer'};
const callbacks=[],messages=[];const setInterval=fn=>(callbacks.push(fn),callbacks.length),clearInterval=()=>{};
const window={addEventListener:()=>{},webkit:{messageHandlers:{systemMedia:{postMessage:v=>messages.push(JSON.parse(v))}}}};
const document={addEventListener:()=>{},title:'Music'};const navigator={mediaSession:null};
const performance={now:()=>2000};class Event{constructor(type){this.type=type;}}
class HTMLMediaElement{play(){return Promise.resolve();}}
let position=42,paused=false,volume=.5;
const node={dispatchEvent:e=>{node.lastEvent=e.type;}};
const sound={_id:7,_node:node,_ended:false};
const h={_state:'loaded',_webAudio:true,_sounds:[sound],seek:function(value,id){if(arguments.length===2||arguments.length===1&&value!==7)position=value;return position;},duration:()=>180,playing:()=>!paused,volume:()=>1,pause:()=>paused=true,play:()=>paused=false,stop:()=>{paused=true;position=0;}};
window.Howler={_howls:[h],volume:function(value){if(arguments.length)volume=value;return volume;}};
window.__musicNativeHowl=()=>h;
''')

    def evaluate(self,source):
        result=self.context.evaluate(source,-1);error=self.context.get_exception()
        self.assertIsNone(error,error.get_message() if error else '')
        return result

    def test_ui_node_reads_the_actual_decoded_clock(self):
        self.evaluate((ROOT/'decoded-media-state.js').read_text())
        data=json.loads(self.evaluate('position=81.5;callbacks[0]();JSON.stringify({time:node.currentTime,duration:node.duration,event:node.lastEvent,end:node.buffered.end(0)})').to_string())
        self.assertEqual(data,{'time':81.5,'duration':180,'event':'timeupdate','end':180})

    def test_ui_seek_writes_go_to_the_decoded_player(self):
        self.evaluate((ROOT/'decoded-media-state.js').read_text())
        self.evaluate('node.currentTime=75')
        self.assertEqual(self.evaluate('position').to_double(),75)

    def test_loading_node_has_no_fake_duration_or_progress(self):
        self.evaluate("h._state='loading'")
        self.evaluate((ROOT/'decoded-media-state.js').read_text())
        self.assertTrue(self.evaluate('Number.isNaN(node.duration)').to_boolean())
        self.assertEqual(self.evaluate('node.currentTime').to_double(),0)

    def test_desktop_bridge_uses_decoded_progress_and_controls(self):
        self.evaluate((ROOT/'system-media.js').read_text())
        data=json.loads(self.evaluate("callbacks[0]();window.__neteaseSystemMedia('seekto',{seekTime:75});JSON.stringify(messages[messages.length-1])").to_string())
        self.assertEqual(data['position'],75)
        self.assertEqual(data['duration'],180)
        self.assertTrue(data['playing'])
        self.evaluate("window.__neteaseSystemMedia('pause',{})")
        self.assertTrue(self.evaluate('paused').to_boolean())

    def test_desktop_loading_does_not_queue_seek_getters(self):
        self.evaluate("h._state='loading';h.seek=()=>{throw new Error('queued seek')}")
        self.evaluate((ROOT/'system-media.js').read_text())
        data=json.loads(self.evaluate('callbacks[0]();JSON.stringify(messages[0])').to_string())
        self.assertEqual(data['position'],0)
        self.assertFalse(data['playing'])
