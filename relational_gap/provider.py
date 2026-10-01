"""One recorded dispatch to the authorized .env provider; no silent retries."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

from dotenv import dotenv_values
import httpx


def encoded(value):
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':')) + '\n').encode()


def write(path, value):
    path.write_bytes(encoded(value))


def dispatch(request, output: Path, *, root: Path):
    output.mkdir(parents=True, exist_ok=False)
    thinking = request.get('thinking', 'disabled')
    if thinking not in {'enabled', 'disabled'}:
        raise ValueError('Unsupported thinking mode')
    max_tokens = request.get('max_tokens', 16384)
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 16384:
        raise ValueError('Unsupported output token budget')
    payload = {'model': 'deepseek-v4-flash', 'temperature': 0, 'max_tokens': max_tokens,
               'messages': [{'role': 'system', 'content': request['system']},
                            {'role': 'user', 'content': request['prompt']}],
               'response_format': {'type': 'json_object'}, 'stream': False,
               'thinking': {'type': thinking}}
    if 'reasoning_effort' in request:
        if request['reasoning_effort'] not in {'low', 'high', 'max'}:
            raise ValueError('Unsupported reasoning effort')
        payload['reasoning_effort'] = request['reasoning_effort']
    write(output/'request.json', payload)
    record = {'request_id': request['id'], 'model': payload['model'],
              'request_sha256': hashlib.sha256(encoded(payload)).hexdigest(),
              'created_at': datetime.now(timezone.utc).isoformat(), 'external_model_calls': 0,
              'thinking': thinking,
              'reference_or_verifier_inputs': False, 'execution_outcomes': False,
              'status': 'prepared', 'timeout_seconds': 300, 'max_response_bytes': 524288}
    if 'max_tokens' in request:
        record['max_output_tokens'] = max_tokens
    if 'reasoning_effort' in payload:
        record['reasoning_effort'] = payload['reasoning_effort']
    write(output/'manifest.json', record)
    policy = json.loads((root/'configs/execution_policy.json').read_text())
    if not policy.get('allow_model_code_upload'):
        raise ValueError('Provider code upload not authorized')
    config = {key.lower(): value for key, value in dotenv_values(root/'.env').items() if value}
    base = config.get('base_url') or config.get('openai_base_url')
    key = config.get('api_key') or config.get('openai_api_key')
    if not base or not key:
        record.update(status='configuration_error')
        write(output/'manifest.json', record)
        return record
    suffix = urlsplit(base).path.rstrip('/')
    route = root/'results/api_route.json'
    prefix = json.loads(route.read_text()).get('prefix', '') if route.exists() else ''
    if suffix.endswith('/v1') or suffix.endswith('/chat/completions'):
        prefix = ''
    url = base.rstrip('/') if suffix.endswith('/chat/completions') else base.rstrip('/') + '/' + prefix + 'chat/completions'
    record['endpoint_sha256'] = hashlib.sha256(url.encode()).hexdigest()
    started = time.monotonic()
    try:
        record.update(status='dispatching', external_model_calls=1)
        write(output/'manifest.json', record)
        body = bytearray()
        with httpx.Client(timeout=300, follow_redirects=False) as client:
            with client.stream('POST', url, headers={'Authorization': 'Bearer ' + key,
                                                     'Content-Type': 'application/json'},
                               content=encoded(payload)) as response:
                record['http_status'] = response.status_code
                for chunk in response.iter_bytes():
                    body.extend(chunk[:524289-len(body)])
                    if len(body) > 524288:
                        raise ValueError('response_byte_budget')
                (output/'response.body').write_bytes(body)
                response.raise_for_status()
        raw = json.loads(body)
        write(output/'response.json', raw)
        choice = raw['choices'][0]
        content = choice['message']['content']
        if not isinstance(content, str):
            raise ValueError('missing_response_content')
        (output/'completion.txt').write_text(content)
        record.update(status='complete', finish_reason=choice.get('finish_reason'),
                      usage=raw.get('usage'), response_model=raw.get('model'))
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        # Exception strings can embed URLs; only safe class identifiers enter logs.
        record.update(status='error', error_type=type(exc).__name__)
    finally:
        record['seconds'] = time.monotonic()-started
        record['response_sha256'] = hashlib.sha256(body).hexdigest()
        write(output/'manifest.json', record)
    return record
