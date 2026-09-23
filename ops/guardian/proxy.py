"""Loopback Responses proxy. Real OpenAI key never enters the agent process."""
import datetime as dt
import http.server
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from common import STATE, read_json, write_json, now

LOCK = threading.Lock()

class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'
    def log_message(self, *args):
        pass
    def fail(self, status, message):
        self.send_response(status); self.send_header('Content-Type','application/json'); self.end_headers()
        self.wfile.write(json.dumps({'error':{'message':message}}).encode())
    def do_POST(self):
        if self.path != '/v1/responses':
            return self.fail(403,'Only Responses requests are permitted')
        try:
            size = int(self.headers.get('Content-Length','0'))
            if not 0 < size <= 200000:
                return self.fail(413,'Request limit exceeded')
            body = json.loads(self.rfile.read(size))
            token = self.headers.get('Authorization','').removeprefix('Bearer ')
            with LOCK:
                caps = read_json(STATE/'capabilities.json',{})
                cap = caps.get(token)
                if not cap or cap['expires'] < time.time():
                    return self.fail(401,'Expired repair capability')
                budget = read_json(STATE/'api-budget.json',{})
                day = now().date().isoformat()
                if budget.get('day') != day:
                    budget = {'day':day,'requests':0,'input_bytes':0}
                if cap.get('requests',0) >= 12 or budget['requests'] >= 30 or budget['input_bytes']+size > 1500000:
                    return self.fail(429,'Guardian daily/per-incident budget exhausted')
                cap['requests'] = cap.get('requests',0)+1
                budget['requests']+=1; budget['input_bytes']+=size
                write_json(STATE/'capabilities.json',caps);write_json(STATE/'api-budget.json',budget)
            conf = read_json('/etc/easystock-guardian/config.json')
            from dotenv import dotenv_values
            credential = dotenv_values('/home/ubuntu/easystock-dual-review.env')['OPENAI_API_KEY']
            body['model'] = conf['model'];body['max_output_tokens'] = 4096;body['store'] = False
            # No hosted tools or background jobs can be requested through this proxy.
            if any(t.get('type') not in ('function','custom') for t in body.get('tools',[])):
                return self.fail(403,'Hosted tools are not allowed')
            body.pop('background',None)
            request = urllib.request.Request('https://api.openai.com/v1/responses', data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+credential,'Content-Type':'application/json'})
            with urllib.request.urlopen(request,timeout=120) as result:
                self.send_response(result.status)
                self.send_header('Content-Type',result.headers.get('Content-Type','application/json'))
                self.end_headers()
                while True:
                    chunk = result.read1(8192)
                    if not chunk:break
                    self.wfile.write(chunk);self.wfile.flush()
        except urllib.error.HTTPError as exc:
            # Do not forward diagnostic headers or credential-related bodies.
            self.fail(exc.code,'OpenAI request failed (HTTP '+str(exc.code)+')')
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            self.fail(502,'Guardian proxy failure: '+type(exc).__name__)

if __name__ == '__main__':
    http.server.ThreadingHTTPServer(('127.0.0.1',18765),Handler).serve_forever()
