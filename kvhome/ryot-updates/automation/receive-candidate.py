#!/usr/bin/env python3
"""Verify a transferred local build, preflight a database copy, and deploy."""
import fcntl
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path('/srv/homelab/ryot')
CONTROL = ROOT / 'automation'


def run(*args, capture=False):
    return subprocess.check_output(args, text=True).strip() if capture else subprocess.run(args, check=True)


def notice(message):
    result = subprocess.run(['sudo', '-n', 'python3', str(CONTROL / 'notify-update.py'), message])
    if result.returncode:
        print('Update result recorded; notification delivery requires attention', file=sys.stderr)


def main():
    incoming = Path(sys.argv[1]).resolve()
    if incoming.parent != ROOT / 'incoming' or not re.fullmatch(r'local-[0-9]+', incoming.name):
        raise ValueError('Invalid incoming update directory')
    with (ROOT / 'receive.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for state in (ROOT / 'updates').glob('*/result'):
            if state.read_text().strip() in ('preparing', 'activating', 'recovery_required'):
                run('docker', 'compose', '--project-directory', str(ROOT), 'stop', 'ryot')
                raise RuntimeError('Previous update needs recovery; Ryot stopped and backups preserved')
        for name in ('manifest.json', 'image.tar.gz', 'source.bundle'):
            path = incoming / name
            if path.is_symlink() or not path.is_file():
                raise ValueError('Missing regular update artifact')
        manifest = json.loads((incoming / 'manifest.json').read_text())
        assert manifest['repository'] == 'kvaranovich/ryot' and manifest['executor'] == 'local-mac' and manifest['status'] == 'built'
        build_id = manifest['build_id']
        assert isinstance(build_id, int) and build_id > 0 and incoming.name == 'local-' + str(build_id)
        for key in ('base', 'fork', 'upstream', 'candidate_commit'):
            assert re.fullmatch('[a-f0-9]{40}', manifest[key])
        for key in ('image_archive_sha256', 'control_sha256', 'patch_sha256'):
            assert re.fullmatch('[a-f0-9]{64}', manifest[key])
        heads = run('git', 'bundle', 'list-heads', str(incoming / 'source.bundle'), capture=True).splitlines()
        assert manifest['candidate_commit'] + ' HEAD' in heads
        image = 'ryot-update:local-' + str(build_id)
        assert manifest['image_tag'] == image
        digest = hashlib.sha256()
        with (incoming / 'image.tar.gz').open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        assert digest.hexdigest() == manifest['image_archive_sha256']
        result_path = ROOT / 'updates' / incoming.name / 'result'
        if result_path.exists():
            if result_path.read_text().strip() == 'deployed':
                print('This validated build is already deployed')
                return
            raise RuntimeError('This candidate failed previously; manual investigation required')
        run('docker', 'load', '--input', str(incoming / 'image.tar.gz'))
        metadata = json.loads(run('docker', 'image', 'inspect', image, capture=True))[0]
        assert metadata['Architecture'] == 'amd64'
        assert metadata['Config']['Labels']['org.opencontainers.image.revision'] == manifest['candidate_commit']
        assert metadata['Config']['Labels']['org.opencontainers.image.source'] == 'https://github.com/kvaranovich/ryot'
        run('bash', str(ROOT / 'preflight-personal-note.sh'), str(incoming / 'image.tar.gz'), image)
        target = 'kvhome/ryot:local-' + str(build_id)
        run('docker', 'tag', image, target)
        run('bash', str(CONTROL / 'deploy-candidate.sh'), target, incoming.name)
        (ROOT / 'updates' / incoming.name / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        source = ROOT / 'source'
        if source.exists() and not run('git', '-C', str(source), 'status', '--porcelain', capture=True):
            run('git', '-C', str(source), 'fetch', str(incoming / 'source.bundle'), 'HEAD')
            run('git', '-C', str(source), 'checkout', '--detach', manifest['candidate_commit'])
        notice('Ryot обновлён после локальной сборки на Mac.\nUpstream: ' + manifest['upstream'][:12] + '\nПроверены тесты, копия БД, восстановление, вход владельца и поиск каталогов.')
        print('Verified local update deployed')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        notice('Обновление Ryot остановлено. Проверка или установка не прошла; автоматическое продолжение отключено. Посмотри локальный журнал обновления.')
        raise SystemExit('Update failed; inspect local protected logs and recovery state') from None
