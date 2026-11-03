"""One recorded DeepSeek request to the project's configured provider."""
import json
from pathlib import Path
import time

from dotenv import dotenv_values
import httpx

from .artifacts import write_json


MODEL = 'deepseek-v4-flash'


def complete(system, prompt, out, *, root, reasoning_effort='high', thinking=True):
    out = Path(out)
    out.mkdir(parents=True)
    config = dotenv_values(Path(root) / '.env')
    endpoint = config['base_url'].rstrip('/') + '/chat/completions'
    request = {'model': MODEL, 'temperature': 0, 'thinking': {'type': 'enabled' if thinking else 'disabled'},
               'response_format': {'type': 'json_object'},
               'stream': False, 'messages': [{'role': 'system', 'content': system},
                                             {'role': 'user', 'content': prompt}]}
    if thinking:
        request['reasoning_effort'] = reasoning_effort
    write_json(out / 'request.json', request)
    started = time.monotonic()
    response = httpx.post(endpoint, headers={'Authorization': 'Bearer ' + config['api_key']},
                          json=request, timeout=1200)
    (out / 'response.body').write_bytes(response.content)
    write_json(out / 'http.json', {'status': response.status_code, 'seconds': time.monotonic() - started})
    response.raise_for_status()
    raw = response.json()
    write_json(out / 'response.json', raw)
    choice = raw['choices'][0]
    (out / 'completion.txt').write_text(choice['message']['content'])
    write_json(out / 'usage.json', {'requested_model': MODEL, 'response_model': raw['model'],
                                   'finish_reason': choice['finish_reason'], 'usage': raw['usage']})
    result = json.loads(choice['message']['content'])
    write_json(out / 'parsed.json', result)
    return result
