#!/usr/bin/env python3
"""Build and test a Linux amd64 Ryot candidate on this Mac in isolated Docker."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import shlex
import shutil

CONTROL = Path(__file__).resolve().parent
ROOT = CONTROL.parent


def control_checksum():
    return hashlib.sha256(b''.join((CONTROL / name).read_bytes() for name in ('build-candidate.sh', 'Dockerfile.builder'))).hexdigest()


def trim_candidates(state):
    directory = state / 'candidates'
    keep = set()
    for name in ('last-built.json', 'last-deployed.json'):
        path = state / name
        if path.exists():
            keep.add(str(json.loads(path.read_text())['build_id']))
    candidates = sorted((p for p in directory.iterdir() if p.name.isdecimal() and p.is_dir() and not p.is_symlink()), key=lambda p: int(p.name), reverse=True) if directory.exists() else []
    keep.update(p.name for p in candidates[:7])
    for path in candidates:
        if path.name not in keep:
            shutil.rmtree(path)


def run(*args, capture=False):
    return subprocess.check_output(args, text=True).strip() if capture else subprocess.run(args, check=True)


def checksum(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def build(candidate, build_id):
    network = 'kvh40-build-' + str(build_id)
    daemon, worker = network + '-docker', network + '-worker'
    certificates = network + '-certificates'
    for volume in ('kvh40-engine-store', 'kvh40-source-cache', 'kvh40-rust-target', 'kvh40-cargo-registry', 'kvh40-cargo-git', certificates):
        run('docker', 'volume', 'create', volume)
    run('docker', 'build', '--platform', 'linux/amd64', '-f', str(CONTROL / 'Dockerfile.builder'), '-t', 'kvhome/ryot-builder:1', str(CONTROL))
    run('docker', 'network', 'create', network)
    try:
        run('docker', 'run', '--detach', '--privileged', '--name', daemon, '--network', network, '--network-alias', 'docker', '--memory', '3g', '--cpus', '2', '-e', 'DOCKER_TLS_CERTDIR=/certs', '-v', certificates + ':/certs', '-v', 'kvh40-engine-store:/var/lib/docker', 'docker:29.8.1-dind')
        run('docker', 'run', '--detach', '--platform', 'linux/amd64', '--name', worker, '--network', 'container:' + daemon, '--memory', '4500m', '--cpus', '4', '-e', 'DOCKER_HOST=tcp://127.0.0.1:2376', '-e', 'DOCKER_TLS_VERIFY=1', '-e', 'DOCKER_CERT_PATH=/certs/client', '-e', 'DOCKER_DEFAULT_PLATFORM=linux/amd64', '-v', certificates + ':/certs:ro', '-v', 'kvh40-source-cache:/build/candidate', '-v', 'kvh40-rust-target:/build/candidate/source/target', '-v', 'kvh40-cargo-registry:/usr/local/cargo/registry', '-v', 'kvh40-cargo-git:/usr/local/cargo/git', '-v', str(CONTROL) + ':/control:ro', 'kvhome/ryot-builder:1')
        for _ in range(60):
            ready = subprocess.run(['docker', 'exec', worker, 'docker', 'info'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if ready.returncode == 0:
                break
            time.sleep(2)
        else:
            raise RuntimeError('Isolated Docker test daemon did not start')
        run('docker', 'exec', worker, 'bash', '-lc', 'find /build/candidate/source -mindepth 1 -maxdepth 1 ! -name target -exec rm -rf -- {} +; rm -rf /build/candidate/artifact')
        run('docker', 'cp', str(candidate / 'source') + '/.', worker + ':/build/candidate/source')
        run('docker', 'cp', str(candidate / 'integration.json'), worker + ':/build/candidate/integration.json')
        control_hash = control_checksum()
        run('docker', 'exec', '-e', 'APP_VERSION=kv-local-' + str(build_id), '-e', 'RYOT_BUILD_ID=' + str(build_id), '-e', 'RYOT_CONTROL_SHA256=' + control_hash, worker, 'bash', '/control/build-candidate.sh', '/build/candidate')
        run('docker', 'cp', worker + ':/build/candidate/artifact', str(candidate / 'artifact'))
        for name in ('manifest.json', 'source.bundle', 'image.tar.gz'):
            path = candidate / 'artifact' / name
            if path.is_symlink() or not path.is_file():
                raise RuntimeError('Expected regular build artifact: ' + name)
        manifest = json.loads((candidate / 'artifact/manifest.json').read_text())
        if manifest['executor'] != 'local-mac' or manifest['control_sha256'] != control_hash:
            raise RuntimeError('Build provenance mismatch')
        if checksum(candidate / 'artifact/image.tar.gz') != manifest['image_archive_sha256']:
            raise RuntimeError('Image archive checksum mismatch')
        manifest['artifact_directory'] = str(candidate / 'artifact')
        return manifest
    finally:
        for name in (worker, daemon):
            subprocess.run(['docker', 'rm', '--force', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(['docker', 'network', 'rm', network], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(['docker', 'volume', 'rm', certificates], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', action='store_true', help='Run full compilation and all tests')
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--deploy', action='store_true', help='Transfer a validated build and run server preflight/deployment')
    parser.add_argument('--ssh-host', help='Existing SSH config alias for the destination server')
    args = parser.parse_args()
    if args.deploy and not valid_host(args.ssh_host):
        parser.error('--deploy requires an existing SSH alias with --ssh-host')
    state = ROOT / '.local-build'
    state.mkdir(exist_ok=True)
    os.chmod(state, 0o700)
    with (state / 'update.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.deploy:
            run('ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', args.ssh_host, 'true')
        trim_candidates(state)
        source = state / 'patch-source'
        if not source.exists():
            run('git', 'clone', '--branch', 'codex/kvh-39', 'https://github.com/kvaranovich/ryot.git', str(source))
        run('git', '-C', str(source), 'fetch', 'origin', 'codex/kvh-39:refs/remotes/origin/codex/kvh-39')
        run('git', '-C', str(source), 'fetch', '--no-tags', 'https://github.com/IgnisDa/ryot.git', 'main:refs/remotes/upstream/main')
        build_id = int(time.time())
        candidate = state / 'candidates' / str(build_id)
        run(sys.executable, str(ROOT / 'prepare-update.py'), '--source', str(source), '--base', 'v10.5.0', '--fork', 'origin/codex/kvh-39', '--upstream', 'upstream/main', '--output', str(candidate))
        current = json.loads((candidate / 'integration.json').read_text())
        current['control_sha256'] = control_checksum()
        previous_path = state / 'last-built.json'
        previous = json.loads(previous_path.read_text()) if previous_path.exists() else {}
        if not args.force and all(previous.get(key) == current[key] for key in ('upstream', 'patch_sha256', 'control_sha256')):
            print('No upstream or patch changes; existing validated build retained')
            if args.deploy:
                deploy(previous, args.ssh_host, state)
            return
        if not args.build:
            print('Candidate prepared; pass --build to compile and run all tests locally')
            return
        manifest = build(candidate, build_id)
        previous_path.write_text(json.dumps(manifest, indent=2) + '\n')
        print('Local Linux amd64 build and all tests passed: ' + manifest['artifact_directory'])
        if args.deploy:
            deploy(manifest, args.ssh_host, state)


def valid_host(host):
    return bool(host) and not host.startswith('-') and all(ch.isalnum() or ch in '._-' for ch in host)


def deploy(manifest, host, state):
    if not valid_host(host):
        raise ValueError('Pass an existing, simple SSH config alias with --ssh-host')
    last_path = state / 'last-deployed.json'
    previous = json.loads(last_path.read_text()) if last_path.exists() else {}
    if previous.get('candidate_commit') == manifest['candidate_commit']:
        print('This candidate is already installed; no deployment needed')
        return
    artifact = Path(manifest['artifact_directory'])
    if state / 'candidates' not in artifact.resolve().parents:
        raise ValueError('Expected locally owned build artifacts')
    for name in ('manifest.json', 'source.bundle', 'image.tar.gz'):
        if (artifact / name).is_symlink() or not (artifact / name).is_file():
            raise ValueError('Missing regular build artifact')
    if checksum(artifact / 'image.tar.gz') != manifest['image_archive_sha256']:
        raise ValueError('Build archive checksum changed')
    source = state / 'patch-source'
    run('git', '-C', str(source), 'fetch', str(artifact / 'source.bundle'), 'HEAD')
    actual = run('git', '-C', str(source), 'rev-parse', 'FETCH_HEAD', capture=True)
    if actual != manifest['candidate_commit']:
        raise ValueError('Source bundle commit mismatch')
    ref = 'refs/heads/codex/local-' + str(manifest['build_id'])
    run('git', '-C', str(source), 'push', 'origin', actual + ':' + ref)
    destination = '/srv/homelab/ryot/incoming/local-' + str(manifest['build_id'])
    run('ssh', '-o', 'BatchMode=yes', host, shlex.join(['mkdir', '-p', destination]))
    run('scp', str(artifact / 'image.tar.gz'), str(artifact / 'manifest.json'), str(artifact / 'source.bundle'), host + ':' + destination + '/')
    run('ssh', '-o', 'BatchMode=yes', host, shlex.join(['python3', '/srv/homelab/ryot/automation/receive-candidate.py', destination]))
    last_path.write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    os.umask(0o077)
    try:
        main()
    except BlockingIOError:
        print('A local update is already running; skipped')
    except Exception:
        if '--ssh-host' in sys.argv:
            host = sys.argv[sys.argv.index('--ssh-host') + 1] if sys.argv.index('--ssh-host') + 1 < len(sys.argv) else None
            if valid_host(host):
                message = 'Обновление Ryot на Mac остановлено до установки. Проверь локальный журнал: конфликт, сборка, тесты или передача не прошли.'
                subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', host, shlex.join(['sudo', '-n', 'python3', '/srv/homelab/ryot/automation/notify-update.py', message])], check=False)
        raise
