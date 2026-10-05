#!/usr/bin/env python3
"""Read-only smoke check of the existing owner's session and private note API."""
import json
import os
from pathlib import Path
import urllib.request

root = Path(os.environ.get('RYOT_ROOT', '/srv/homelab/ryot'))
endpoint = os.environ.get('RYOT_GRAPHQL_URL', 'http://127.0.0.1:18038/backend/graphql')
token = json.loads((root / 'owner-session.json').read_text())['token']
query = 'query { userDetails { ...on UserDetails { id lot isDisabled } } personalNote(metadataId:"__update_read_only_probe__") { text } }'


def request(authorization=None):
    headers = {'Content-Type': 'application/json'}
    if authorization:
        headers['Authorization'] = 'Bearer ' + authorization
    req = urllib.request.Request(endpoint, json.dumps({'query': query}).encode(), headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


result = request(token)
assert not result.get('errors'), 'Owner smoke check failed; private response suppressed'
assert result['data']['userDetails']['lot'] == 'NORMAL'
assert not result['data']['userDetails']['isDisabled']
assert result['data']['personalNote'] is None
assert request().get('errors'), 'Anonymous access unexpectedly accepted'
print('Owner session, ordinary role, private note API and anonymous rejection OK')
