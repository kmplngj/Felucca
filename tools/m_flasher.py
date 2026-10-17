#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Install/reuse a reviewed native MIDI CLI in a private user cache; no device access."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile

REPOSITORY = 'kmplngj/m-flasher'
REVISION = 'ed44c15d5f9b049fd326a1331953c7bf4a1c87e2'
PROTOCOL = 'felucca-device-pull-v1'


def host_platform():
    system, machine = platform.system(), platform.machine().lower()
    if system == 'Darwin' and machine in ('arm64', 'aarch64', 'x86_64'):
        return 'macos'
    if system == 'Linux' and machine in ('x86_64', 'amd64'):
        return 'linux-x86_64'
    if system == 'Windows' and machine in ('x86_64', 'amd64'):
        return 'windows-x86_64'
    raise ValueError(f'No prebuilt MIDI CLI for {system}/{machine}; build the pinned source and use --m-flasher PATH')


def binary_name():
    return 'm-flasher.exe' if os.name == 'nt' else 'm-flasher'


def cache_directory():
    return Path.home() / '.local' / 'share' / 'felucca' / 'm-flasher' / REVISION / host_platform()


def run(arguments, timeout=120):
    try:
        result = subprocess.run([str(a) for a in arguments], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(f'Cannot run {arguments[0]}: {error}') from error
    if result.returncode:
        detail = re.sub(r'(https?://[^\s?]+)\?[^\s]+', r'\1?[query redacted]', result.stderr.strip())
        raise ValueError(f'{arguments[0]} failed: {detail or result.returncode}')
    return result.stdout


def check_capabilities(binary):
    try:
        value = json.loads(run([binary, '--capabilities'], timeout=15))
    except (ValueError, TypeError) as error:
        raise ValueError(f'{binary}: no compatible native MIDI CLI; run python3 tools/m_flasher.py or select --installer python. {error}') from error
    if not isinstance(value, dict) or value.get('schema') != 1 or value.get('midi_ota') is not True or value.get('protocol') != PROTOCOL:
        raise ValueError(f'{binary}: missing native MIDI OTA capability; use the reviewed MIDI CLI')
    return Path(binary)


def verify_directory(directory):
    binary = directory / binary_name()
    manifest = directory / 'source.json'
    if manifest.is_symlink() or binary.is_symlink() or not manifest.is_file() or not binary.is_file():
        raise ValueError('M-Flasher installation lacks regular binary/source.json files')
    if manifest.stat().st_size > 16384 or binary.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('M-Flasher installation exceeds expected bounds')
    try:
        source = json.loads(manifest.read_text())
    except (ValueError, OSError) as error:
        raise ValueError('Invalid M-Flasher source manifest') from error
    if not isinstance(source, dict) or any(source.get(key) != expected for key, expected in (
            ('repository', REPOSITORY), ('revision', REVISION), ('platform', host_platform()),
            ('binary', binary_name()))):
        raise ValueError('M-Flasher artifact does not match the pinned source/platform')
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    if source.get('sha256') != digest:
        raise ValueError('M-Flasher executable SHA-256 mismatch; refusing to execute it')
    return binary


def download(directory):
    endpoint = f'repos/{REPOSITORY}/actions/workflows/midi.yml/runs?event=push&head_sha={REVISION}&per_page=100'
    data = json.loads(run(['gh', 'api', endpoint]))
    runs = sorted((r for r in data['workflow_runs'] if r['head_sha'] == REVISION
                   and r['event'] == 'push' and r['status'] == 'completed' and r['conclusion'] == 'success'),
                  key=lambda r: r['id'], reverse=True)
    artifact_name = f'm-flasher-midi-{host_platform()}'
    for workflow in runs:
        artifacts = json.loads(run(['gh', 'api', f'repos/{REPOSITORY}/actions/runs/{workflow["id"]}/artifacts']))['artifacts']
        matches = [a for a in artifacts if a['name'] == artifact_name and not a['expired']]
        if len(matches) == 1:
            run(['gh', 'run', 'download', str(workflow['id']), '--repo', REPOSITORY,
                 '--name', artifact_name, '--dir', str(directory)], timeout=300)
            return
    raise ValueError('No live successful native MIDI artifact for the pinned source. '
                     'Run python3 tools/m_flasher.py --from-source with Rust installed, '
                     'or use --m-flasher PATH / --installer python. No firmware build was requested.')


def build_source(directory):
    run(['cargo', 'install', '--git', f'https://github.com/{REPOSITORY}.git', '--rev', REVISION,
         '--locked', '--root', str(directory / 'cargo'), 'm-flasher-midi'], timeout=1200)
    binary = directory / binary_name()
    os.replace(directory / 'cargo' / 'bin' / binary_name(), binary)
    source = {'repository': REPOSITORY, 'revision': REVISION, 'platform': host_platform(),
              'binary': binary_name(), 'sha256': hashlib.sha256(binary.read_bytes()).hexdigest()}
    (directory / 'source.json').write_text(json.dumps(source, indent=2) + '\n')


def ensure(executable=None, from_source=False):
    if executable:
        return check_capabilities(Path(executable).expanduser().resolve())
    destination = cache_directory()
    if destination.exists():
        return check_capabilities(verify_directory(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f'Installing native MIDI CLI ({REPOSITORY}@{REVISION[:12]})...', flush=True)
    with tempfile.TemporaryDirectory(prefix='m-flasher-', dir=destination.parent) as temporary:
        staged = Path(temporary) / 'install'
        staged.mkdir()
        (build_source if from_source else download)(staged)
        binary = verify_directory(staged)
        binary.chmod(0o755)
        check_capabilities(binary)  # Offline; never enumerates or opens MIDI ports.
        try:
            os.replace(staged, destination)
        except OSError:
            # Another helper may have completed the same immutable install.
            if not destination.exists():
                raise
            check_capabilities(verify_directory(destination))
    return destination / binary_name()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-source', action='store_true', help='build the pinned CLI with Cargo instead of downloading a live CI artifact')
    options = parser.parse_args(argv)
    try:
        print(ensure(from_source=options.from_source))
        return 0
    except (ValueError, OSError, KeyError) as error:
        print(f'error: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
