#!/usr/bin/env python3
"""Report Ryot upstream changes monthly from the server without building."""
import argparse
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

ROOT = Path('/srv/homelab/ryot')
API = 'https://api.github.com/repos/IgnisDa/ryot/'


def github(path):
    request = urllib.request.Request(API + path, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'Ryot-monthly-update-check'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def installed_upstream():
    records = (ROOT / 'updates/deployments.jsonl').read_text().splitlines()
    record = json.loads(records[-1])
    deployment = record['deployment']
    if not re.fullmatch(r'[a-zA-Z0-9._-]+', deployment):
        raise ValueError('Invalid local deployment record')
    manifest = json.loads((ROOT / 'updates' / deployment / 'manifest.json').read_text())
    commit = manifest['upstream']
    if not re.fullmatch('[a-f0-9]{40}', commit):
        raise ValueError('Invalid installed upstream commit')
    return commit


def summary(month, installed, comparison, release):
    total = comparison['total_commits']
    lines = ['Ryot: обзор обновлений за ' + month, 'Установленный upstream: ' + installed[:12]]
    if not total:
        lines.append('Новых изменений после установленной версии нет. Пересборка сейчас не нужна.')
    else:
        lines.append('Новых коммитов: ' + str(total) + '. Решение о пересборке остаётся за тобой.')
        titles = [' '.join(c['commit']['message'].splitlines()[0].split())[:160] for c in comparison.get('commits', [])]
        notable = [title for title in titles if re.search(r'(?i)feat|fix|perf|support|improv|security|add', title)]
        for title in (notable or titles)[-5:]:
            lines.append('• ' + title)
        lines.append('Все изменения: https://github.com/IgnisDa/ryot/compare/' + installed + '...main')
    if release:
        lines.append('Последний релиз: ' + release['tag_name'])
        lines.append('https://github.com/IgnisDa/ryot/releases/tag/' + urllib.parse.quote(release['tag_name'], safe=''))
    lines.append('Сборка и тесты запускаются вручную на Mac, готовый образ отправляется на сервер. Автоустановка отключена.')
    return '\n'.join(lines)


def notify(message):
    subprocess.run(['sudo', '-n', 'python3', str(ROOT / 'automation/notify-update.py'), message], check=True)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview', action='store_true', help='Print the report without sending or recording it')
    args = parser.parse_args()
    month = datetime.now(ZoneInfo('Europe/Warsaw')).strftime('%Y-%m')
    state = ROOT / 'updates/monthly-report.json'
    with (ROOT / 'updates/monthly-report.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not args.preview and state.exists() and json.loads(state.read_text())['month'] == month:
            print('This month was already reported')
            return
        installed = installed_upstream()
        comparison = github('compare/' + installed + '...main')
        try:
            release = github('releases/latest')
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            release = None
        message = summary(month, installed, comparison, release)
        if args.preview:
            print(message)
            return
        notify(message)
        state.write_text(json.dumps({'month': month, 'installed_upstream': installed, 'compared_upstream': comparison['commits'][-1]['sha'] if comparison.get('commits') else installed, 'new_commits': comparison['total_commits']}, indent=2) + '\n')
        print('Monthly upstream report delivered; no build or deployment performed')


if __name__ == '__main__':
    try:
        main()
    except BlockingIOError:
        print('Monthly report is already running')
    except Exception:
        month = datetime.now(ZoneInfo('Europe/Warsaw')).strftime('%Y-%m')
        if '--preview' not in sys.argv:
            try:
                notify('Ryot: не удалось проверить обновления за ' + month + '. Сборка и установка не запускались. Проверь журнал ryot-monthly-updates.service на сервере.')
            except Exception:
                pass
        raise SystemExit('Monthly check failed; private responses suppressed') from None
