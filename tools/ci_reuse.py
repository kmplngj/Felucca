#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Fail-closed receipts for the standalone, identity-independent backup fixture.

Only backup-checks is eligible: its fixed command imports fm1backup.js and uses
simulated devices, without filesystem, environment or Git identity dependencies.
Firmware, host and browser jobs embed the compiled checkout identity and remain
fresh. Receipts are evidence, never replacement firmware or fresh test invocations.
Restore uses gh's authentication and only fixed same-repository API endpoints.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile

SCHEMA = 1
JOB = 'backup-checks'
WORKFLOW = '.github/workflows/ci.yml'
SHA = re.compile(r'[0-9a-f]{40}')
REPOSITORY = re.compile(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/(?!\.{1,2}$)[A-Za-z0-9_.-]{1,100}')
MAX_CANDIDATES = 3
MAX_BYTES = 2 * 1024 * 1024
ENVIRONMENT = ('FELUCCA_PROFILE', 'NODE_OPTIONS', 'NODE_PATH', 'NODE_EXTRA_CA_CERTS',
               'NODE_ICU_DATA', 'OPENSSL_CONF', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ',
               'ImageOS', 'ImageVersion', 'RUNNER_OS', 'RUNNER_ARCH')
LOADER_OVERRIDES = ('LD_PRELOAD', 'LD_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES', 'DYLD_LIBRARY_PATH')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


def sources(root):
    """Hash bytes actually read, modes and recursively checked-out gitlinks."""
    if git(root, 'status', '--porcelain', '--untracked-files=normal').strip():
        raise ValueError('reuse requires clean sources and initialized clean submodules')
    rows = []
    for entry in git(root, 'ls-files', '--stage', '-z').split(b'\0'):
        if not entry:
            continue
        metadata, name = entry.split(b'\t', 1)
        mode, oid, stage = metadata.decode().split()
        if stage != '0':
            raise ValueError('unmerged source input')
        name = os.fsdecode(name)
        path = root / name
        if mode == '160000':
            revision = git(path, 'rev-parse', 'HEAD').decode().strip()
            if revision != oid:
                raise ValueError('submodule revision differs from pinned input')
            rows.append([name, mode, revision, sources(path)])
        elif mode in ('100644', '100755'):
            actual_mode = path.lstat().st_mode
            if not stat.S_ISREG(actual_mode):
                raise ValueError('source input must be a regular file')
            executable = bool(actual_mode & stat.S_IXUSR)
            if executable != (mode == '100755'):
                raise ValueError('source executable mode differs from index')
            rows.append([name, mode, digest(path.read_bytes())])
        else:
            # No symlink resolution or files outside the checkout in a receipt.
            raise ValueError('unsupported source input mode')
    if not rows:
        raise ValueError('empty source input set')
    if git(root, 'status', '--porcelain', '--untracked-files=normal').strip():
        raise ValueError('source inputs changed while fingerprinting')
    return rows


def runtime(env):
    node = shutil.which('node', path=env.get('PATH'))
    if not node:
        raise ValueError('Node is required for backup evidence')
    node = Path(node).resolve()
    # NODE_OPTIONS can preload arbitrary modules before the fixed fixture starts.
    # Refuse overrides rather than pretending their file dependencies are covered.
    for name in (*ENVIRONMENT, *LOADER_OVERRIDES):
        if (name.startswith(('NODE_', 'OPENSSL_')) or name in LOADER_OVERRIDES) and env.get(name):
            raise ValueError(f'{name} is not permitted for reusable backup evidence')
    return {'node_sha256': digest(node.read_bytes()),
            'node_versions': json.loads(subprocess.check_output(
                [str(node), '-p', 'JSON.stringify(process.versions)'], env=env)),
            'platform': [platform.system(), platform.release(), platform.machine()],
            'os_release': Path('/etc/os-release').read_text() if Path('/etc/os-release').is_file() else None,
            'environment': {name: env.get(name) for name in ENVIRONMENT}}


def origin(root, env):
    revision = git(root, 'rev-parse', 'HEAD').decode().strip()
    if not SHA.fullmatch(revision):
        raise ValueError('invalid source revision')
    event_name = env.get('GITHUB_EVENT_NAME')
    if env.get('GITHUB_ACTIONS') != 'true' or event_name not in ('push', 'pull_request'):
        raise ValueError('reuse receipts require automatic CI')
    event = json.loads(Path(env['GITHUB_EVENT_PATH']).read_text())
    repository = env['GITHUB_REPOSITORY']
    if not REPOSITORY.fullmatch(repository) or event['repository']['full_name'] != repository:
        raise ValueError('event repository mismatch')
    head = revision
    if event_name == 'pull_request':
        pr = event['pull_request']
        if pr['head']['repo']['full_name'] != repository or pr['base']['repo']['full_name'] != repository:
            raise ValueError('fork evidence is not trusted for reuse')
        head = pr['head']['sha']
        headers = git(root, 'show', '-s', '--format=raw', 'HEAD').split(b'\n\n', 1)[0].splitlines()
        if f'parent {head}'.encode() not in headers:
            raise ValueError('compiled PR revision does not contain event head')
    if revision != env.get('GITHUB_SHA') or not SHA.fullmatch(head):
        raise ValueError('compiled revision differs from CI event')
    run_id, attempt = env['GITHUB_RUN_ID'], env['GITHUB_RUN_ATTEMPT']
    if not re.fullmatch(r'[1-9][0-9]*', run_id) or not re.fullmatch(r'[1-9][0-9]*', attempt):
        raise ValueError('invalid CI run identity')
    return {'repository': repository, 'revision': revision, 'head_sha': head,
            'event': event_name, 'run_id': int(run_id), 'run_attempt': int(attempt),
            'workflow': WORKFLOW, 'job': JOB}


def snapshot(root, job, env):
    if job != JOB:
        raise ValueError('only standalone backup-checks has proven identity-independent inputs')
    if env.get('VERSION') or env.get('RELEASE_VALIDATION') == 'true' or env.get('GITHUB_REF_TYPE') == 'tag':
        raise ValueError('release evidence always runs fresh')
    inputs = sources(root)
    required = {WORKFLOW, '.github/workflows/build.yml', 'tools/ci_reuse.py',
                'web/test_backup.mjs', 'web/fm1backup.js'}
    if not required <= {row[0] for row in inputs}:
        raise ValueError('backup fixture, workflow and reuse helper must be tracked inputs')
    data = {'schema': SCHEMA, 'job': job, 'command': ['node', 'web/test_backup.mjs'],
            'sources': inputs, 'runtime': runtime(env),
            'helper_sha256': digest(Path(__file__).read_bytes()),
            'git_metadata': 'not applicable: standalone simulated-device backup fixture'}
    return {'schema': SCHEMA, 'inputs': data, 'fingerprint': digest(canonical(data)),
            'origin': origin(root, env)}


def validate_snapshot(data):
    source = data['origin']
    if (data['schema'] != SCHEMA or data['inputs']['schema'] != SCHEMA or
            data['inputs']['job'] != JOB or data['origin']['job'] != JOB or
            data['inputs']['command'] != ['node', 'web/test_backup.mjs'] or
            source['workflow'] != WORKFLOW or source['event'] not in ('push', 'pull_request') or
            not REPOSITORY.fullmatch(source['repository']) or
            not SHA.fullmatch(source['revision']) or not SHA.fullmatch(source['head_sha']) or
            type(source['run_id']) is not int or source['run_id'] <= 0 or
            type(source['run_attempt']) is not int or source['run_attempt'] <= 0 or
            data['fingerprint'] != digest(canonical(data['inputs']))):
        raise ValueError('invalid backup input snapshot')


def evidence(path):
    if not path.is_file() or path.is_symlink() or not path.stat().st_size:
        raise ValueError('missing or empty backup test evidence')
    return {'name': path.name, 'sha256': digest(path.read_bytes())}


def record(root, expected, log, env):
    validate_snapshot(expected)
    current = snapshot(root, JOB, env)
    if current != expected:
        raise ValueError('backup inputs or run changed after test start')
    return {'schema': SCHEMA, 'status': 'passed', 'snapshot': expected, 'evidence': evidence(log)}


def verify(expected, receipt, run, evidence_root):
    validate_snapshot(expected)
    tested = receipt['snapshot']
    validate_snapshot(tested)
    source = tested['origin']
    if receipt['schema'] != SCHEMA or receipt['status'] != 'passed':
        raise ValueError('receipt is not a successful backup execution')
    if expected['fingerprint'] != tested['fingerprint'] or expected['inputs'] != tested['inputs']:
        raise ValueError('backup inputs do not match prior evidence')
    if (run['status'] != 'completed' or run['conclusion'] != 'success' or
            run['id'] != source['run_id'] or run['run_attempt'] != source['run_attempt'] or
            run['head_sha'] != source['head_sha'] or run['event'] != source['event'] or
            run['event'] not in ('pull_request', 'push') or run['path'] != WORKFLOW or
            run['repository']['full_name'] != source['repository'] or
            run['head_repository']['full_name'] != source['repository'] or
            source['repository'] != expected['origin']['repository']):
        raise ValueError('prior run is not successful trusted same-repository CI')
    item = receipt['evidence']
    if not isinstance(item['name'], str) or Path(item['name']).name != item['name'] or item['name'] in ('.', '..'):
        raise ValueError('invalid evidence filename')
    if evidence(evidence_root / item['name']) != item:
        raise ValueError('backup evidence checksum mismatch')
    return {'reused': True, **source, 'fingerprint': tested['fingerprint'],
            'url': f"https://github.com/{source['repository']}/actions/runs/{source['run_id']}/attempts/{source['run_attempt']}"}


def gh_api(endpoint, timeout=3):
    """Bound both response bytes and process time; never expose gh's stderr."""
    # The caller builds endpoints from a validated repository and numeric IDs.
    # Fixing the hostname also prevents GH_HOST from redirecting authentication.
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(['gh', 'api', '--hostname', 'github.com',
                                    '--method', 'GET', endpoint],
                                   stdout=output, stderr=subprocess.DEVNULL,
                                   env=os.environ | {'GH_PROMPT_DISABLED': '1'})
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                if os.fstat(output.fileno()).st_size > MAX_BYTES or time.monotonic() >= deadline:
                    raise ValueError('GitHub API response exceeded limits')
                try:
                    process.wait(timeout=0.05)
                except subprocess.TimeoutExpired:
                    pass
            if process.returncode or os.fstat(output.fileno()).st_size > MAX_BYTES:
                raise ValueError('GitHub API request unavailable or oversized')
            output.seek(0)
            return output.read(MAX_BYTES + 1)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


def trusted_run(run, repository):
    return (type(run['id']) is int and run['id'] > 0 and
            type(run['run_attempt']) is int and run['run_attempt'] > 0 and
            run['status'] == 'completed' and run['conclusion'] == 'success' and
            run['event'] in ('pull_request', 'push') and run['path'] == WORKFLOW and
            run['repository']['full_name'] == repository and
            run['head_repository']['full_name'] == repository)


def unpack_receipt(payload, directory):
    """Read exactly the two bounded regular files, without extractall or links."""
    if len(payload) > MAX_BYTES:
        raise ValueError('oversized backup receipt archive')
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = archive.infolist()
        if len(members) != 2 or {item.filename for item in members} != {'receipt.json', 'backup-tests.log'}:
            raise ValueError('unexpected backup receipt archive members')
        if sum(item.file_size for item in members) > MAX_BYTES:
            raise ValueError('oversized expanded backup receipt')
        for item in members:
            mode = item.external_attr >> 16
            if (item.is_dir() or item.flag_bits & 1 or
                    stat.S_IFMT(mode) not in (0, stat.S_IFREG) or item.file_size <= 0):
                raise ValueError('backup receipt members must be nonempty regular files')
        for item in members:
            content = archive.read(item)
            if len(content) != item.file_size:
                raise ValueError('invalid backup receipt member size')
            (directory / item.filename).write_bytes(content)


def restore(root, expected, directory, env):
    """Look up an exact input fingerprint; uncertainty retains fresh validation."""
    validate_snapshot(expected)
    if snapshot(root, JOB, env) != expected:
        raise ValueError('current backup inputs differ from requested snapshot')
    destination = directory if directory.is_absolute() else root / directory
    if not destination.resolve().is_relative_to(root.resolve() / 'build') or destination.is_symlink():
        raise ValueError('backup restore directory must be under ignored build output')
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError('backup restore directory must be empty')
    repository = expected['origin']['repository']
    prefix = f'repos/{repository}/actions'
    deadline = time.monotonic() + 10

    def api(endpoint):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('backup receipt lookup budget exhausted')
        return gh_api(endpoint, timeout=min(3, remaining))

    name = f"backup-receipt-{expected['fingerprint']}"
    artifacts = json.loads(api(f'{prefix}/artifacts?name={name}&per_page={MAX_CANDIDATES}&page=1'))['artifacts']
    if not isinstance(artifacts, list):
        raise ValueError('invalid backup artifact listing')
    inspected = 0
    for artifact in artifacts[:MAX_CANDIDATES]:
        if time.monotonic() >= deadline:
            break
        try:
            if (artifact['name'] != name or artifact['expired'] is not False or
                    type(artifact['id']) is not int or artifact['id'] <= 0 or
                    type(artifact['size_in_bytes']) is not int or
                    not 0 < artifact['size_in_bytes'] <= MAX_BYTES):
                continue
            run_id = artifact['workflow_run']['id']
            if type(run_id) is not int or not 0 < run_id < expected['origin']['run_id']:
                continue
            inspected += 1
            # Fetch current metadata for the receipt's originating run. Never
            # accept inherited receipts relabeled by a later artifact producer.
            run = json.loads(api(f'{prefix}/runs/{run_id}'))
            if run['id'] != run_id or not trusted_run(run, repository):
                continue
            payload = api(f"{prefix}/artifacts/{artifact['id']}/zip")
            with tempfile.TemporaryDirectory(prefix='candidate-', dir=destination) as temporary:
                candidate = Path(temporary)
                unpack_receipt(payload, candidate)
                receipt = json.loads((candidate / 'receipt.json').read_text())
                if receipt['snapshot']['origin']['run_id'] != run_id:
                    continue
                result = verify(expected, receipt, run, candidate)
                # Recheck current inputs before making the skip decision visible.
                if snapshot(root, JOB, env) != expected:
                    raise ValueError('backup inputs changed during restore')
                for filename in ('receipt.json', 'backup-tests.log'):
                    (destination / filename).write_bytes((candidate / filename).read_bytes())
                (destination / 'run.json').write_text(json.dumps(run, indent=2) + '\n')
                (destination / 'reuse.json').write_text(json.dumps(result, indent=2) + '\n')
                return result
        except (ValueError, OSError, KeyError, TypeError, AttributeError, zipfile.BadZipFile,
                RuntimeError, NotImplementedError, subprocess.SubprocessError):
            # Unavailable, malformed or mismatching candidates cannot waive work.
            continue
    return {'reused': False, 'reason': f'no valid exact-input backup receipt in {inspected} eligible artifacts'}


def restore_output(result, env):
    if output := env.get('GITHUB_OUTPUT'):
        with open(output, 'a') as stream:
            stream.write(f"reused={str(result['reused']).lower()}\n")
            if result['reused']:
                for key in ('run_id', 'run_attempt', 'revision', 'job', 'url'):
                    stream.write(f'source_{key}={result[key]}\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('snapshot', 'record', 'verify', 'restore'))
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--job', default=JOB)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--run', type=Path)
    parser.add_argument('--evidence-root', type=Path)
    parser.add_argument('--directory', type=Path)
    args = parser.parse_args()
    try:
        if args.job != JOB:
            raise ValueError('only standalone backup-checks has proven identity-independent inputs')
        if args.command == 'snapshot':
            result = snapshot(args.root, args.job, os.environ)
        elif args.command == 'record':
            result = record(args.root, json.loads(args.snapshot.read_text()), args.evidence, os.environ)
        elif args.command == 'restore':
            try:
                result = restore(args.root, json.loads(args.snapshot.read_text()), args.directory, os.environ)
            except (ValueError, OSError, KeyError, TypeError, AttributeError, zipfile.BadZipFile,
                    RuntimeError, NotImplementedError, subprocess.SubprocessError):
                result = {'reused': False, 'reason': 'backup evidence lookup unavailable; run fresh'}
            restore_output(result, os.environ)
        else:
            expected = json.loads(args.snapshot.read_text())
            if snapshot(args.root, args.job, os.environ) != expected:
                raise ValueError('current backup inputs differ from requested snapshot')
            result = verify(expected, json.loads(args.receipt.read_text()),
                            json.loads(args.run.read_text()), args.evidence_root)
        output = json.dumps(result, indent=2, sort_keys=True) + '\n'
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(output)
        else:
            print(output, end='')
    except (ValueError, OSError, KeyError, TypeError, AttributeError, subprocess.SubprocessError) as error:
        # Restore errors are an optimization miss, including output setup errors.
        if args.command == 'restore':
            try:
                restore_output({'reused': False}, os.environ)
            except OSError:
                pass
            print('Backup evidence reuse unavailable; run selected checks fresh', file=sys.stderr)
            return 0
        print(f'CI evidence reuse unavailable: {error}; run selected checks fresh', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
