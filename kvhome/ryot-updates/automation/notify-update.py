#!/usr/bin/env python3
"""Deliver update notices through the existing homelab owner's alert bot."""
import hashlib
import json
import os
from pathlib import Path
import sys
import urllib.parse
import urllib.request

os.umask(0o077)
message = sys.argv[1]
state = Path('/srv/homelab/ryot/updates/last-notification')
digest = hashlib.sha256(message.encode()).hexdigest()
if state.exists() and state.read_text().strip() == digest:
    sys.exit(0)
secrets = Path('/srv/homelab/secrets')
token = (secrets / 'telegram_alert_bot_token').read_text().strip()
chat_id = (secrets / 'telegram_alert_chat_id').read_text().strip()
request = urllib.request.Request('https://api.telegram.org/bot' + token + '/sendMessage', urllib.parse.urlencode({'chat_id': chat_id, 'text': message}).encode())
try:
    with urllib.request.urlopen(request, timeout=20) as response:
        assert json.load(response)['ok']
except Exception:
    raise SystemExit('Update notification delivery failed; private URL suppressed') from None
state.parent.mkdir(exist_ok=True)
state.write_text(digest + '\n')
