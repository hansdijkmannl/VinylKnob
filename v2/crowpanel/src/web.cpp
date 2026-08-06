// ---------------------------------------------------------------------------
// The panel's own settings page. Entirely offline: no CDN, no external fonts.
// ---------------------------------------------------------------------------

#include "web.h"

#include <ArduinoJson.h>
#include <WebServer.h>
#include <WiFi.h>

#include "config.h"
#include "marantz.h"
#include "settings.h"
#include "ui.h"

bool rebootRequested = false;

static WebServer server(80);

// Inputs as the Denon/Marantz protocol names them. Not every one is configured
// on every receiver; what is really there is whatever "SI?" reports back.
static const char *KNOWN_INPUTS[] = {
  "PHONO", "CD", "TUNER", "DVD", "BD", "TV", "SAT/CBL", "MPLAY", "GAME",
  "8K", "AUX1", "AUX2", "NET", "BT", "USB", "HDRADIO", "SPOTIFY", "IRADIO",
  "SERVER", "FAVORITES",
};

static const char PAGE_HTML[] PROGMEM = R"HTML(
<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MarantzKnob</title>
<style>
:root{--bg:#f6f6f7;--fg:#1a1a1c;--card:#fff;--line:#dcdce0;--dim:#6b6b73;--acc:#0a6cff}
@media(prefers-color-scheme:dark){:root{--bg:#16161a;--fg:#e8e8ea;--card:#1f1f25;--line:#33333c;--dim:#9a9aa4}}
*{box-sizing:border-box}
body{margin:0;padding:1.2rem;background:var(--bg);color:var(--fg);
 font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
main{max-width:640px;margin:0 auto}
h1{font-size:1.3rem;margin:0 0 1rem}
h2{font-size:.8rem;text-transform:uppercase;letter-spacing:.08em;color:var(--dim);
 margin:1.6rem 0 .6rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:1rem}
.st{display:flex;flex-wrap:wrap;gap:.5rem 1.4rem;align-items:baseline}
.vol{font-size:2.2rem;font-weight:600;font-variant-numeric:tabular-nums}
.pill{font-size:.72rem;padding:.16rem .5rem;border-radius:99px;border:1px solid var(--line);color:var(--dim)}
.pill.on{background:var(--acc);border-color:var(--acc);color:#fff}
.pill.warn{background:#c0392b;border-color:#c0392b;color:#fff}
label{display:block;margin:.8rem 0 .2rem;font-size:.85rem;color:var(--dim)}
input,select{width:100%;padding:.5rem .6rem;border:1px solid var(--line);border-radius:7px;
 background:var(--bg);color:var(--fg);font:inherit}
input[type=range]{padding:0;border:0;background:transparent;accent-color:var(--acc);height:1.6rem}
.sl{display:flex;align-items:baseline;gap:.6rem}
.sl output{min-width:4.5rem;text-align:right;font-variant-numeric:tabular-nums;
 font-weight:600;font-size:.9rem}
.row{display:flex;gap:.6rem;flex-wrap:wrap}.row>*{flex:1;min-width:8rem}
.irow{display:grid;grid-template-columns:1.6rem 1fr 1fr 2rem;gap:.5rem;
 align-items:center;margin-bottom:.45rem}
.irow>span{color:var(--dim);font-size:.85rem;text-align:center}
.irow button{margin:0;padding:.4rem 0;background:transparent;border:1px solid var(--line);
 color:var(--dim);font-size:1rem;line-height:1}
button{margin-top:1.2rem;padding:.6rem 1.1rem;border:0;border-radius:7px;
 background:var(--acc);color:#fff;font:inherit;font-weight:600;cursor:pointer}
button.sec{background:transparent;color:var(--fg);border:1px solid var(--line);font-weight:400}
.hint{font-size:.8rem;color:var(--dim);margin:.4rem 0 0}
dl{margin:0;font-size:.85rem}
dt{font-weight:600;margin-top:.5rem}
dd{margin:0;color:var(--dim)}
#msg{margin-top:.8rem;font-size:.85rem;min-height:1.2em}
</style></head><body><main>
<h1>MarantzKnob</h1>

<div class="card st">
  <span class="vol" id="vol">--</span>
  <span id="inp" style="font-weight:600">-</span>
  <span class="pill" id="pConn">link</span>
  <span class="pill" id="pPwr">standby</span>
  <span class="pill" id="pMute">mute</span>
  <span class="pill" id="pRssi">wifi</span>
</div>

<h2>Receiver</h2>
<div class="card">
  <div class="row">
    <div style="flex:3"><label>IP or hostname</label><input id="avrHost" placeholder="192.168.1.60"></div>
    <div style="flex:1"><label>Port</label><input id="avrPort" type="number"></div>
  </div>
  <p class="hint">In the receiver menu set <b>Network &rsaquo; Network Control</b> to
  &ldquo;Always On&rdquo;, or port 23 disappears in standby.</p>
</div>

<h2>Display</h2>
<div class="card">
  <div class="row">
    <div style="flex:2"><label>Brightness</label>
      <div class="sl"><input id="brightness" type="range" min="10" max="255">
      <output id="oBright"></output></div></div>
    <div style="flex:1"><label>Orientation</label>
      <select id="rotated"><option value="0">normal</option>
      <option value="1">upside down</option></select></div>
      <div style="flex:1"><label>Fine angle (&deg;)</label>
        <input id="screenAngle" type="number" min="-15" max="15" step="0.1"></div>
    <div style="flex:1"><label>Dim after</label>
      <div class="sl"><input id="dimAfterS" type="range" min="0" max="300" step="15">
      <output id="oDim"></output></div></div>
    <div style="flex:1"><label>Follow the amplifier</label>
      <select id="offWithAmp"><option value="1">screen off when the amp is off</option>
      <option value="0">always on</option></select></div>
  </div>
  <p class="hint">Dragging applies immediately so you can see what you are doing. Still press
  save, or it reverts on the next restart.</p>
</div>

<h2>Brain</h2>
<div class="card">
  <div class="row">
    <div style="flex:3"><label>IP of the Pi</label><input id="brainHost" placeholder="192.168.1.175"></div>
  </div>
  <p class="hint">The Pi that listens along and recognises records. Leave empty if you have
  none; the display then shows volume and input only.</p>
</div>

<h2>Volume</h2>
<div class="card">
  <div class="row">
    <div><label>Step per click</label>
      <div class="sl"><input id="halfDbPerClick" type="range" min="1" max="10">
      <output id="oStep"></output></div></div>
    <div><label>Fast-turn boost</label>
      <div class="sl"><input id="accelFactor" type="range" min="1" max="16">
      <output id="oAccel"></output></div></div>
  </div>
  <div class="row">
    <div><label>&ldquo;Fast&rdquo; = clicks within</label>
      <div class="sl"><input id="accelWindowMs" type="range" min="60" max="600" step="10">
      <output id="oWin"></output></div></div>
    <div><label>Volume ceiling</label>
      <div class="sl"><input id="volMaxDb" type="range" min="-40" max="0">
      <output id="oMax"></output></div></div>
    <div><label>Encoder resolution</label>
      <select id="encDivider"><option value="4">1 step per detent (coarse)</option>
      <option value="2">2&times; finer</option>
      <option value="1">4&times; finer (smooth)</option></select></div>
  </div>
  <p class="hint">Half a dB per click is finely adjustable; at 2 or 3 you reach
  the right level quicker. The ceiling is an emergency brake &mdash; 0 dB is
  wide open. With an encoder that has <b>no</b> detents, set the resolution
  finer, or a smoothly turning knob still feels notchy.</p>
</div>

<h2>Inputs</h2>
<div class="card">
  <p class="hint" style="margin:0 0 .7rem">The list you step through by holding the knob and turning. The order below is
  the direction of rotation.</p>
  <div id="ilist"></div>
  <button class="sec" id="addBtn" onclick="addInput()" style="margin-top:.6rem">Add input</button>
  <label>Favourite (double press)</label>
  <select id="favouriteInput"></select>
</div>

<h2>Controls</h2>
<div class="card">
  <div class="row">
    <div><label>Hold for on/off (ms)</label><input id="longPressMs" type="number" min="400" max="3000" step="50"></div>
    <div><label>Double-press window (ms, 0 = off)</label><input id="doublePressMs" type="number" min="0" max="800" step="50"></div>
  </div>
  <p class="hint">With the double-press window at 0, mute responds immediately
  instead of after that window &mdash; but the favourite stops working.</p>
  <dl style="margin-top:1rem">
    <dt>turn</dt><dd>volume</dd>
    <dt>hold + turn</dt><dd>step through inputs</dd>
    <dt>short press</dt><dd>mute on/off</dd>
    <dt>double press</dt><dd>jump to the favourite input</dd>
    <dt>hold</dt><dd>main zone on/off</dd>
    <dt>hold 8 seconds</dt><dd>clear wifi, boot into setup mode</dd>
  </dl>
</div>

<h2>Wi-Fi</h2>
<div class="card">
  <div class="row">
    <div><label>Network (SSID)</label><input id="wifiSsid"></div>
    <div><label>Password</label><input id="wifiPass" type="password" placeholder="unchanged"></div>
  </div>
  <p class="hint">Leave empty to keep the current password. The board restarts after a change.</p>
</div>

<div class="row" style="margin-top:.6rem">
  <button onclick="save()">Save</button>
  <button class="sec" onclick="test()">Test first input</button>
  <button class="sec" onclick="reboot()">Restart</button>
</div>
<div id="msg"></div>
</main><script>
let CODES=[],MAXI=8,inputs=[];
const $=i=>document.getElementById(i);
const esc=s=>String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');
const msg=(t,ok)=>{const m=$('msg');m.textContent=t;m.style.color=ok?'var(--acc)':'#c0392b'};

function renderInputs(){
  $('ilist').innerHTML=inputs.map((b,i)=>
    `<div class="irow"><span>${i+1}</span>
     <select onchange="inputs[${i}].code=this.value;renderFav()">${CODES.map(c=>
       `<option${c===b.code?' selected':''}>${esc(c)}</option>`).join('')}</select>
     <input value="${esc(b.label)}" oninput="inputs[${i}].label=this.value;renderFav()">
     <button onclick="delInput(${i})" title="remove">&times;</button></div>`).join('');
  $('addBtn').style.display=inputs.length>=MAXI?'none':'';
  renderFav();
}
function renderFav(){
  const cur=parseInt($('favouriteInput').dataset.sel??'-1',10);
  $('favouriteInput').innerHTML='<option value="-1">none</option>'+inputs.map((b,i)=>
    `<option value="${i}"${i===cur?' selected':''}>${esc(b.label||b.code)}</option>`).join('');
}
function setFav(v){$('favouriteInput').dataset.sel=v;renderFav()}
function addInput(){if(inputs.length<MAXI){inputs.push({code:CODES[0],label:CODES[0]});renderInputs()}}
function delInput(i){inputs.splice(i,1);setFav(-1);renderInputs()}

async function boot(){
  CODES=await(await fetch('api/inputs')).json();
  const S=await(await fetch('api/settings')).json();
  MAXI=S.maxInputs||8;
  for(const k of ['avrHost','brainHost','brightness','dimAfterS','avrPort','halfDbPerClick','accelFactor','accelWindowMs',
                  'volMaxDb','longPressMs','doublePressMs','wifiSsid'])$(k).value=S[k];
  $('encDivider').value=String(S.encDivider||4);
  // Here and not in renderInputs(): S is local to this function, and that line
  // there threw a ReferenceError which meant the input list, the favourite
  // picker and the status row never appeared at all.
  $('rotated').value=S.rotated?'1':'0';
  $('screenAngle').value=((S.screenAngle||0)/10).toFixed(1);
  $('offWithAmp').value=S.offWithAmp?'1':'0';
  inputs=S.inputs.map(b=>({code:b.code,label:b.label}));
  setFav(S.favouriteInput);
  renderInputs();
  $('favouriteInput').onchange=e=>setFav(parseInt(e.target.value,10));
  tick();setInterval(tick,1000);
}

async function tick(){
  try{
    const s=await(await fetch('api/state')).json();
    $('vol').textContent=s.haveVolume?s.volDb.toFixed(1)+' dB':'--';
    $('inp').textContent=s.inputLabel;
    $('pConn').className='pill '+(s.connected?'on':'warn');
    $('pConn').textContent=s.connected?'receiver':'no receiver';
    $('pPwr').className='pill '+(s.powered?'on':'');
    $('pPwr').textContent=s.powered?'on':'standby';
    $('pMute').className='pill '+(s.muted?'warn':'');
    $('pMute').textContent=s.muted?'muted':'sound';
    $('pRssi').className='pill '+(!s.ap&&s.rssi<-72?'warn':'');
    $('pRssi').textContent=s.ap?'setup AP':s.rssi+' dBm';
  }catch(e){}
}

async function save(){
  const b={inputs:inputs,favouriteInput:parseInt($('favouriteInput').value,10)};
  for(const k of ['avrHost','brainHost','wifiSsid','wifiPass'])b[k]=$(k).value;
  for(const k of ['avrPort','brightness','dimAfterS','halfDbPerClick','accelFactor','accelWindowMs',
                  'volMaxDb','longPressMs','doublePressMs'])b[k]=parseInt($(k).value,10);
  b.encDivider=parseInt($('encDivider').value,10);
  b.rotated=$('rotated').value==='1';
  b.screenAngle=Math.round(parseFloat($('screenAngle').value||'0')*10);
  b.offWithAmp=$('offWithAmp').value==='1';
  const r=await(await fetch('api/settings',{method:'POST',body:JSON.stringify(b)})).json();
  if(!r.ok){msg('Error: '+r.error,false);return}
  $('wifiPass').value='';
  msg(r.wifiChanged?'Saved. Restart needed for the new Wi-Fi.':'Saved.',true);
}

async function test(){
  if(!inputs.length){msg('No inputs configured.',false);return}
  const c=inputs[0].code;
  const r=await(await fetch('api/command?cmd=SI'+encodeURIComponent(c),{method:'POST'})).json();
  msg(r.ok?'SI'+c+' sent.':'No connection to the receiver.',r.ok);
}

async function reboot(){
  await fetch('api/reboot',{method:'POST'});
  msg('Restarting…',true);
}
boot();

// ---- schuiven ------------------------------------------------------------
// The value sits beside it in plain language; brightness goes to the panel
// immediately so you see what you are setting instead of saving and looking.
const SLIDERS = {
  brightness:     [ 'oBright', v => Math.round(v/255*100) + '%' ],
  dimAfterS:      [ 'oDim',    v => +v === 0 ? 'never' : v + ' s' ],
  halfDbPerClick: [ 'oStep',   v => (v/2).toFixed(1) + ' dB' ],
  accelFactor:    [ 'oAccel',  v => '\u00d7' + v ],
  accelWindowMs:  [ 'oWin',    v => v + ' ms' ],
  volMaxDb:       [ 'oMax',    v => v + ' dB' ],
};
function slLabels() {
  for (const [id, [out, fmt]] of Object.entries(SLIDERS))
    if ($(id) && $(out)) $(out).textContent = fmt($(id).value);
}
let slTimer = null;
for (const id of Object.keys(SLIDERS)) {
  const el = $(id); if (!el) continue;
  el.addEventListener('input', () => {
    slLabels();
    if (id !== 'brightness') return;
    clearTimeout(slTimer);
    slTimer = setTimeout(() => fetch('api/settings', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({brightness: +el.value})}), 120);
  });
}
</script></body></html>
)HTML";

// ---------------------------------------------------------------------------
// Routes
// ---------------------------------------------------------------------------
static void handleRoot() {
  server.send_P(200, "text/html; charset=utf-8", PAGE_HTML);
}

static void handleGetSettings() {
  String out;
  settingsToJson(out);
  server.send(200, "application/json", out);
}

static void handlePostSettings() {
  const String body = server.hasArg("plain") ? server.arg("plain") : String();
  String err;
  bool wifiChanged = false;

  JsonDocument res;
  if (settingsFromJson(body, err, wifiChanged)) {
    res["ok"] = true;
    res["wifiChanged"] = wifiChanged;
    // A new address? Reconnect right away rather than waiting.
    avrReconnect();
  } else {
    res["ok"] = false;
    res["error"] = err;
  }

  String out;
  serializeJson(res, out);
  server.send(200, "application/json", out);
}

static void handleState() {
  JsonDocument doc;
  doc["connected"]  = avrState.connected;
  doc["powered"]    = avrState.powered;
  doc["muted"]      = avrState.muted;
  doc["haveVolume"] = avrState.haveVolume;
  doc["volDb"]      = avrState.volHalfSteps / 2.0f - 80.0f;
  doc["input"]      = avrState.input;
  doc["inputLabel"] = avrState.inputLabel;
  doc["ap"]         = netApMode;
  doc["rssi"]       = netApMode ? 0 : WiFi.RSSI();
  doc["ip"]         = netApMode ? WiFi.softAPIP().toString() : WiFi.localIP().toString();
  doc["uptimeS"]    = millis() / 1000;

  // Which screen is showing. The web interface renders a copy of this panel
  // and could until now only guess what was on it; with this field that copy is
  // right in the input list and with the screen off too.
  doc["screen"] = uiScreenName();


  String out;
  serializeJson(doc, out);
  server.send(200, "application/json", out);
}

static void handleInputs() {
  JsonDocument doc;
  JsonArray arr = doc.to<JsonArray>();
  for (const char *c : KNOWN_INPUTS) arr.add(c);
  String out;
  serializeJson(doc, out);
  server.send(200, "application/json", out);
}

static void handleCommand() {
  const bool ok = server.hasArg("cmd") && avrSend(server.arg("cmd").c_str());
  server.send(200, "application/json", ok ? "{\"ok\":true}" : "{\"ok\":false}");
}

static void handleReboot() {
  server.send(200, "application/json", "{\"ok\":true}");
  rebootRequested = true;
}

void webBegin() {
  server.on("/",             HTTP_GET,  handleRoot);
  server.on("/api/settings", HTTP_GET,  handleGetSettings);
  server.on("/api/settings", HTTP_POST, handlePostSettings);
  server.on("/api/state",    HTTP_GET,  handleState);
  server.on("/api/inputs",   HTTP_GET,  handleInputs);
  server.on("/api/command",  HTTP_POST, handleCommand);
  server.on("/api/reboot",   HTTP_POST, handleReboot);

  // In access-point mode everything points at the settings page, so your
  // phone's captive-portal window shows the right thing immediately.
  server.onNotFound([]() {
    if (netApMode) handleRoot();
    else           server.send(404, "text/plain", "not found");
  });

  server.begin();
}

void webLoop() {
  server.handleClient();
}
