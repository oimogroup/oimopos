"""Capture the real local UI with isolated fixtures. Standard library + Chrome only.

Run: python3 scripts/capture_user_guide.py [--pdf]
Never authenticates to a company. All API calls in the capture browser are mocked;
write requests are rejected. The Chrome profile is temporary.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import time
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/user-guide'
AUDIT = ROOT / '.runtime/audit/user-guide-20261022'
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
BASE = 'http://127.0.0.1:8000'


class CDP:
    def __init__(self, url):
        u = urlsplit(url)
        self.sock = socket.create_connection((u.hostname, u.port), timeout=20)
        nonce = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f'GET {u.path} HTTP/1.1\r\nHost: {u.netloc}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {nonce}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
        response = b''
        while not response.endswith(b'\r\n\r\n'):
            response += self.sock.recv(1)
        if response.split(b' ', 2)[1] != b'101':
            raise RuntimeError(response.decode())
        self.seq = 0

    def read(self, length):
        data = b''
        while len(data) < length:
            chunk = self.sock.recv(length-len(data))
            if not chunk:
                raise RuntimeError('Chrome disconnected')
            data += chunk
        return data

    def call(self, method, params=None):
        self.seq += 1
        payload = json.dumps({'id': self.seq, 'method': method, 'params': params or {}}).encode()
        length, mask = len(payload), os.urandom(4)
        header = bytes([129, 128 | length]) if length < 126 else (bytes([129, 254])+struct.pack('!H', length) if length < 65536 else bytes([129, 255])+struct.pack('!Q', length))
        self.sock.sendall(header+mask+bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))
        fragments = b''
        while True:
            first, second = self.read(2)
            length = second & 127
            if length == 126: length = struct.unpack('!H', self.read(2))[0]
            if length == 127: length = struct.unpack('!Q', self.read(8))[0]
            frame_mask = self.read(4) if second & 128 else None
            frame = self.read(length)
            if frame_mask: frame = bytes(b ^ frame_mask[i % 4] for i, b in enumerate(frame))
            if first & 15 == 8: raise RuntimeError('WebSocket closed')
            fragments += frame
            if not first & 128: continue
            result = json.loads(fragments); fragments = b''
            if result.get('id') != self.seq: continue
            if 'error' in result: raise RuntimeError(result['error'])
            return result.get('result', {})

    def js(self, source):
        result = self.call('Runtime.evaluate', {'expression': '(async()=>{'+source+'})()', 'awaitPromise': True, 'returnByValue': True})
        if 'exceptionDetails' in result:
            raise RuntimeError(result['exceptionDetails'].get('exception', {}).get('description', result['exceptionDetails']))
        return result.get('result', {}).get('value')


def main():
    import sys
    AUDIT.mkdir(parents=True, exist_ok=True)
    (OUT/'screenshots').mkdir(parents=True, exist_ok=True)
    profile = tempfile.TemporaryDirectory(prefix='oimo-guide-')
    log = open(AUDIT/'chrome.log', 'w')
    browser = subprocess.Popen([CHROME, '--headless', '--disable-gpu', '--no-first-run', '--remote-debugging-port=0', '--user-data-dir='+profile.name, 'about:blank'], stdout=log, stderr=log)
    try:
        active = Path(profile.name)/'DevToolsActivePort'
        for _ in range(100):
            if active.exists(): break
            time.sleep(.1)
        port = active.read_text().splitlines()[0]
        req = urllib.request.Request(f'http://127.0.0.1:{port}/json/new?about:blank', method='PUT')
        page = json.load(urllib.request.urlopen(req))
        cdp = CDP(page['webSocketDebuggerUrl'])
        cdp.call('Page.enable'); cdp.call('Runtime.enable')
        cdp.call('Emulation.setDeviceMetricsOverride', {'width': 1440, 'height': 1000, 'deviceScaleFactor': 1, 'mobile': False})
        cdp.call('Emulation.setTimezoneOverride', {'timezoneId': 'Asia/Almaty'})
        if '--pdf' in sys.argv:
            cdp.call('Page.navigate', {'url': (OUT/'index.html').as_uri()})
            time.sleep(2)
            cdp.js("document.querySelectorAll('img').forEach(i=>i.loading='eager');await document.fonts.ready; await Promise.all([...document.images].map(i=>i.complete?Promise.resolve():new Promise(r=>{i.onload=r;i.onerror=r})));document.querySelectorAll('details').forEach(d=>d.open=true);return true;")
            result = cdp.call('Page.printToPDF', {'printBackground': True, 'preferCSSPageSize': True, 'displayHeaderFooter': False, 'generateDocumentOutline': True})
            (OUT/'Oimo-user-guide.pdf').write_bytes(base64.b64decode(result['data']))
            print('PDF saved', flush=True)
            return
        state = json.loads(subprocess.check_output([
            'docker', 'compose', 'run', '--rm', '--no-deps', '-e', 'DATABASE_URL=', 'api', 'python', '-c',
            'import json; from app.workspace import default_state; print(json.dumps(default_state(),ensure_ascii=False))'
        ], cwd=ROOT))
        bootstrap = 'window.__GUIDE_STATE__='+json.dumps(state, ensure_ascii=False)+';\n'+(ROOT/'scripts/user-guide-demo.js').read_text()
        cdp.call('Page.addScriptToEvaluateOnNewDocument', {'source': bootstrap})
        scenes = json.loads((ROOT/'scripts/user-guide-scenes.json').read_text())
        manifest = []
        start = sys.argv[sys.argv.index('--from')+1] if '--from' in sys.argv else ''
        only = set(sys.argv[sys.argv.index('--only')+1].split(',')) if '--only' in sys.argv else set()
        for scene in scenes:
            if only and scene['id'] not in only: continue
            if start and scene['id'] < start: continue
            cdp.call('Page.navigate', {'url': BASE+scene['url']})
            for _ in range(70):
                time.sleep(.1)
                if cdp.js("return document.readyState==='complete' && (location.pathname==='/login'||(location.pathname==='/admin'?typeof renderAll==='function':Boolean(document.querySelector('#branchSelect option'))));"): break
            if scene['url'].startswith('/admin'):
                cdp.js("currentSession.name='Демо · Владелец';currentSession.tenantName='Демо-кафе';hydrateServerWorkspace({version:1,state:window.__GUIDE_STATE__});employees=window.__GUIDE_EMPLOYEES__;posRegisters=window.__GUIDE_REGISTERS__;renderAll();")
            cdp.js(scene.get('script', '')+';return true;')
            time.sleep(.35)
            result = cdp.js("await document.fonts.ready;"+"const markers="+json.dumps(scene.get('markers', []), ensure_ascii=False)+";const result=[];document.querySelectorAll('[data-guide-mark]').forEach(n=>n.remove());for(const [i,m] of markers.entries()){const el=document.querySelector(m.selector);if(!el)throw new Error('Missing target '+m.selector);const r=el.getBoundingClientRect();if(!r.width||!r.height)throw new Error('Hidden target '+m.selector);el.style.outline='3px solid #8e4bf1';el.style.outlineOffset='3px';const badge=document.createElement('b');badge.dataset.guideMark='true';badge.textContent=i+1;badge.style='position:fixed;z-index:2147483647;display:grid;place-items:center;width:28px;height:28px;background:#6d3fd0;color:white;border:2px solid white;border-radius:50%;font:700 15px Arial;box-shadow:0 2px 8px #30204444;pointer-events:none;left:'+Math.max(4,Math.min(1400,r.left-10))+'px;top:'+Math.max(4,Math.min(958,r.top-13))+'px';(document.querySelector('dialog[open]')||document.body).append(badge);result.push({number:i+1,...m});}const badge=document.createElement('div');badge.dataset.guideMark='true';badge.textContent='ДЕМОНСТРАЦИОННЫЕ ДАННЫЕ · OIMO';badge.style='position:fixed;bottom:6px;left:50%;transform:translateX(-50%);z-index:2147483647;padding:5px 12px;background:#ffffffed;border:1px solid #dacfea;border-radius:20px;font:10px Arial;color:#71578d;pointer-events:none';(document.querySelector('dialog[open]')||document.body).append(badge);return result;")
            image = cdp.call('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': False})
            filename = scene['id']+'.png'
            path = OUT/'screenshots'/filename
            path.write_bytes(base64.b64decode(image['data']))
            manifest.append({'id': scene['id'], 'title': scene['title'], 'url': scene['url'], 'image':'screenshots/'+filename, 'markers':result, 'sha256':hashlib.sha256(path.read_bytes()).hexdigest(), 'demo':True})
            print('Captured '+scene['id'], flush=True)
        manifest = [{**{k:scene[k] for k in ('id','title','url')}, 'image':'screenshots/'+scene['id']+'.png', 'markers':[{'number':i+1,**m} for i,m in enumerate(scene['markers'])], 'sha256':hashlib.sha256((OUT/'screenshots'/(scene['id']+'.png')).read_bytes()).hexdigest(), 'demo':True} for scene in scenes if (OUT/'screenshots'/(scene['id']+'.png')).exists()]
        (OUT/'screenshots/manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    finally:
        browser.terminate()
        try: browser.wait(timeout=10)
        except subprocess.TimeoutExpired: browser.kill(); browser.wait()
        log.close()
        profile.cleanup()


if __name__ == '__main__': main()
