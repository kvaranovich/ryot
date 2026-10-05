#!/usr/bin/env python3
"""Install the validated Mac updater and its daily LaunchAgent."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess

SOURCE = Path(__file__).resolve().parent.parent


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ssh-host', required=True)
    args = parser.parse_args()
    if not args.ssh_host or args.ssh_host.startswith('-') or not all(c.isalnum() or c in '._-' for c in args.ssh_host):
        parser.error('Expected an existing SSH alias')
    state = SOURCE / '.local-build'
    with (state / 'update.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        built = json.loads((state / 'last-built.json').read_text())
        deployed = json.loads((state / 'last-deployed.json').read_text())
        if built['candidate_commit'] != deployed['candidate_commit'] or built['status'] != 'built':
            raise RuntimeError('First local build, tests and deployment must pass before scheduling')
        target = Path.home() / '.local/share/kvhome/ryot-updates'
        if target.exists() and any(target.iterdir()) and not (target / 'installation.json').exists():
            raise RuntimeError('Installation directory is already used by another setup')
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        (target / 'automation').mkdir(exist_ok=True, mode=0o700)
        for path in (SOURCE / 'automation').iterdir():
            if path.is_file() and (path.suffix in ('.py', '.sh') or path.name == 'Dockerfile.builder'):
                shutil.copy2(path, target / 'automation' / path.name)
        shutil.copy2(SOURCE / 'prepare-update.py', target / 'prepare-update.py')
        target_state = target / '.local-build'
        target_state.mkdir(exist_ok=True, mode=0o700)
        for name in ('last-built.json', 'last-deployed.json'):
            manifest = json.loads((state / name).read_text())
            candidate = state / 'candidates' / str(manifest['build_id'])
            destination = target_state / 'candidates' / candidate.name
            if not destination.exists():
                shutil.copytree(candidate, destination, symlinks=True)
            manifest['artifact_directory'] = str(destination / 'artifact')
            (target_state / name).write_text(json.dumps(manifest, indent=2) + '\n')
        if not (target_state / 'patch-source').exists():
            shutil.copytree(state / 'patch-source', target_state / 'patch-source', symlinks=True)
        (target / 'installation.json').write_text(json.dumps({'source': str(SOURCE), 'ssh_host': args.ssh_host, 'candidate_commit': built['candidate_commit']}, indent=2) + '\n')
    label = 'org.kvhome.ryot-updates'
    agents = Path.home() / 'Library/LaunchAgents'
    agents.mkdir(parents=True, exist_ok=True)
    plist = agents / (label + '.plist')
    value = {
        'Label': label,
        'ProgramArguments': ['/usr/bin/caffeinate', '-i', '/usr/bin/python3', str(target / 'automation/local-update.py'), '--build', '--deploy', '--ssh-host', args.ssh_host],
        'WorkingDirectory': str(target),
        'EnvironmentVariables': {'PATH': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'},
        'StartCalendarInterval': {'Hour': 10, 'Minute': 0},
        'StandardOutPath': str(target_state / 'scheduled.log'),
        'StandardErrorPath': str(target_state / 'scheduled.log'),
        'ProcessType': 'Background',
        'ThrottleInterval': 3600,
    }
    plist.write_bytes(plistlib.dumps(value))
    domain = 'gui/' + str(os.getuid())
    subprocess.run(['launchctl', 'bootout', domain + '/' + label], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(['launchctl', 'bootstrap', domain, str(plist)], check=True)
    subprocess.run(['launchctl', 'kickstart', domain + '/' + label], check=True)
    print('Daily Mac updater installed; initial background check started')
    print(target_state / 'scheduled.log')


if __name__ == '__main__':
    main()
