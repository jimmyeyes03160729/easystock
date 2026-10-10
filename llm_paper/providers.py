"""三家 LLM 的 REST 呼叫（OpenAI Responses、Anthropic Messages、Gemini generateContent），皆開啟網路搜尋。

金鑰只從環境變數讀（VM 上的 /home/ubuntu/easystock/.env），不寫進任何輸出檔。
每家回傳 (text, meta)；失敗時丟出例外，由呼叫端記錄為該家當天無名單。
"""
import os
import time

import requests

TIMEOUT = (10, 240)


def env(*names, default=''):
    for n in names:
        v = os.environ.get(n, '').strip()
        if v:
            return v
    return default


def _post(url, headers, body):
    last = None
    for attempt in range(3):
        try:
            r = requests.post(url, headers=headers, json=body, timeout=TIMEOUT)
        except requests.RequestException as exc:
            last = '%s' % type(exc).__name__
        else:
            if r.status_code == 200:
                return r.json()
            last = 'HTTP %s: %s' % (r.status_code, r.text[:300])
            if r.status_code not in (429, 500, 502, 503, 504, 529):
                break
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(last)


def ask_openai(prompt):
    model = env('LLM_PAPER_OPENAI_MODEL', default='gpt-5')
    data = _post('https://api.openai.com/v1/responses',
                 {'Authorization': 'Bearer ' + env('OPENAI_API_KEY'), 'Content-Type': 'application/json'},
                 {'model': model, 'input': prompt, 'tools': [{'type': 'web_search'}]})
    text = ''.join(c.get('text', '') for item in data.get('output', []) if item.get('type') == 'message'
                   for c in item.get('content', []) if c.get('type') == 'output_text')
    return text, {'model': data.get('model', model), 'usage': data.get('usage')}


def ask_anthropic(prompt):
    model = env('LLM_PAPER_ANTHROPIC_MODEL', default='claude-opus-5-5')
    headers = {'x-api-key': env('ANTHROPIC_API_KEY'), 'anthropic-version': '2023-06-01', 'content-type': 'application/json'}
    messages = [{'role': 'user', 'content': prompt}]
    for _ in range(4):                       # server-side web search may pause a long turn; resend to continue
        data = _post('https://api.anthropic.com/v1/messages', headers,
                     {'model': model, 'max_tokens': 8000, 'messages': messages,
                      'tools': [{'type': 'web_search_20250305', 'name': 'web_search', 'max_uses': 8}]})
        if data.get('stop_reason') != 'pause_turn':
            break
        messages = [messages[0], {'role': 'assistant', 'content': data['content']}]
    text = ''.join(b.get('text', '') for b in data.get('content', []) if b.get('type') == 'text')
    return text, {'model': data.get('model', model), 'usage': data.get('usage'), 'stop_reason': data.get('stop_reason')}


def ask_gemini(prompt):
    model = env('LLM_PAPER_GEMINI_MODEL', default='gemini-3.1-pro-preview')
    data = _post('https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent' % model,
                 {'x-goog-api-key': env('GEMINI_API_KEY', 'GOOGLE_API_KEY'), 'Content-Type': 'application/json'},
                 {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}], 'tools': [{'google_search': {}}]})
    cands = data.get('candidates') or [{}]
    text = ''.join(p.get('text', '') for p in (cands[0].get('content') or {}).get('parts', []))
    return text, {'model': data.get('modelVersion', model), 'usage': data.get('usageMetadata'),
                  'finish_reason': cands[0].get('finishReason')}


PROVIDERS = {'openai': (ask_openai, ('OPENAI_API_KEY',)),
             'claude': (ask_anthropic, ('ANTHROPIC_API_KEY',)),
             'gemini': (ask_gemini, ('GEMINI_API_KEY', 'GOOGLE_API_KEY'))}
