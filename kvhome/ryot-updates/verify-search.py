import json
from pathlib import Path
import urllib.request

root = Path('/srv/homelab/ryot')
token = json.loads((root / 'owner-session.json').read_text())['token']
env = dict(line.split('=', 1) for line in (root / 'ryot.env').read_text().splitlines() if '=' in line)
keys = ('MOVIES_AND_SHOWS_TMDB_ACCESS_TOKEN', 'VIDEO_GAMES_TWITCH_CLIENT_ID', 'VIDEO_GAMES_TWITCH_CLIENT_SECRET')
if not all(env.get(key) for key in keys):
    raise SystemExit('Provider setup incomplete; no secrets printed')
query = 'query($input:MetadataSearchInput!){metadataSearch(input:$input){response{items}}}'
for lot, source, title in [('MOVIE', 'TMDB', 'Interstellar'), ('SHOW', 'TMDB', 'Breaking Bad'), ('VIDEO_GAME', 'IGDB', 'The Witcher 3'), ('BOOK', 'OPENLIBRARY', 'Crime and Punishment')]:
    variables = {'input': {'lot': lot, 'source': source, 'search': {'query': title, 'page': 1, 'take': 5}}}
    request = urllib.request.Request('http://127.0.0.1:18038/backend/graphql', json.dumps({'query': query, 'variables': variables}).encode(), {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.load(response)
    if data.get('errors'):
        print(lot, source, 'FAILED; provider response suppressed')
        raise SystemExit(1)
    count = len(data['data']['metadataSearch']['response']['items'])
    assert count > 0, 'No results from ' + source
    print(lot, source, 'search OK; results:', count)
