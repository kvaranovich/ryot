"""Exercise Personal Note only on the isolated local preflight instance."""
import json
import os
from pathlib import Path
import urllib.request
from uuid import uuid4

ENDPOINT = os.environ.get('RYOT_PREFLIGHT_ENDPOINT', 'http://127.0.0.1:18039/backend/graphql')
assert ENDPOINT in ('http://127.0.0.1:18039/backend/graphql', 'http://kvh39-preflight-app:8000/backend/graphql')
ROOT = Path('/srv/homelab/ryot')
OWNER_TOKEN = json.loads((ROOT / 'owner-session.json').read_text())['token']
FIXTURE_TEXT = 'personal-note-recovery-fixture'


def request(query, variables=None, token=None, expect_error=False):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(ENDPOINT, json.dumps({
        'query': query, 'variables': variables or {}
    }).encode(), headers)
    with urllib.request.urlopen(req, timeout=60) as response:
        result = json.load(response)
    if expect_error:
        assert result.get('errors'), 'Unauthenticated operation was accepted'
        return
    if result.get('errors'):
        raise RuntimeError('Preflight GraphQL operation failed; no private response printed')
    return result['data']


name = 'personal_note_preflight_' + uuid4().hex
password = uuid4().hex
registration = request('mutation($input:RegisterUserInput!){registerUser(input:$input){__typename}}', {
    'input': {'data': {'password': {'username': name, 'password': password}}}
})
assert registration['registerUser']['__typename'] == 'StringIdObject', 'Test user registration failed'
login = request('mutation($input:AuthUserInput!){loginUser(input:$input){...on ApiKeyResponse{apiKey}}}', {
    'input': {'password': {'username': name, 'password': password}}
})
other_token = login['loginUser']['apiKey']
metadata_id = request('mutation($input:CreateCustomMetadataInput!){createCustomMetadata(input:$input){id}}', {
    'input': {'lot': 'BOOK', 'title': 'Personal Note preflight fixture', 'assets': {
        's3Images': [], 's3Videos': [], 'remoteImages': [], 'remoteVideos': []
    }}
}, OWNER_TOKEN)['createCustomMetadata']['id']
variables = {'id': metadata_id}
read = 'query($id:String!){personalNote(metadataId:$id){text createdAt updatedAt}}'
save = 'mutation($id:String!,$text:String!){setPersonalNote(metadataId:$id,text:$text){text createdAt updatedAt}}'
delete = 'mutation($id:String!){deletePersonalNote(metadataId:$id)}'
ratings = 'query($id:String!){userMetadataDetails(metadataId:$id){response{averageRating reviews{id}}}}'
before = request(ratings, variables, OWNER_TOKEN)
created = request(save, {**variables, 'text': 'Initial note'}, OWNER_TOKEN)['setPersonalNote']
assert request(read, variables, other_token)['personalNote'] is None
updated = request(save, {**variables, 'text': FIXTURE_TEXT}, OWNER_TOKEN)['setPersonalNote']
assert updated['createdAt'] == created['createdAt']
assert updated['text'] == FIXTURE_TEXT
assert request(delete, variables, other_token)['deletePersonalNote'] is False
request(save, {**variables, 'text': 'Independent note'}, other_token)
assert request(read, variables, OWNER_TOKEN)['personalNote']['text'] == FIXTURE_TEXT
assert request(delete, variables, other_token)['deletePersonalNote'] is True
assert request(read, variables, OWNER_TOKEN)['personalNote']['text'] == FIXTURE_TEXT
assert request(ratings, variables, OWNER_TOKEN) == before
for operation, values in [(read, variables), (save, {**variables, 'text': 'Anonymous'}), (delete, variables)]:
    request(operation, values, expect_error=True)
assert request(delete, variables, OWNER_TOKEN)['deletePersonalNote'] is True
assert request(read, variables, OWNER_TOKEN)['personalNote'] is None
request(save, {**variables, 'text': FIXTURE_TEXT}, OWNER_TOKEN)
print('Personal Note image preflight: owner CRUD, user isolation, authentication and unchanged ratings OK')
print('One synthetic note retained in the isolated database for backup recovery verification')
