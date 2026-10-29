#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Build one reviewed current-HEAD profile in isolated Git and Git-free trees.

Workflow admission is main-only; explicit local mode is a maintainer operation,
not a GitHub review attestation. This driver never publishes or installs firmware.
"""
import os as _source_os

# This entry point intentionally requires Git, unlike the producers it invokes.
# Reject an extracted archive before it can import unverified repository helpers.
if _source_os.path.isfile(_source_os.path.join(_source_os.path.dirname(
        _source_os.path.dirname(_source_os.path.realpath(__file__))), 'SOURCE-PINS.json')):
    raise SystemExit('maintainer orchestration requires a clean committed Git checkout')

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile

import build_manifest
import profile
import source_archive

REPOSITORY = 'kmplngj/Felucca'
PROFILES = ('standard', 'reduced-lofi', 'macro')
REVISION = re.compile(r'[0-9a-f]{40}')
HOOKS = ('NODE_OPTIONS', 'NODE_PATH', 'EMU_OPT', 'EMU_CFLAGS', 'EMU_PREVIEW')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def admission(mode, revision, environment):
    require(REVISION.fullmatch(revision) is not None, 'revision must be a full lowercase commit SHA')
    if mode == 'workflow':
        require(environment.get('GITHUB_ACTIONS') == 'true' and
                environment.get('GITHUB_EVENT_NAME') == 'workflow_dispatch' and
                environment.get('GITHUB_REPOSITORY') == REPOSITORY and
                environment.get('GITHUB_REF') == 'refs/heads/main' and
                environment.get('GITHUB_SHA') == revision and
                environment.get('GITHUB_WORKFLOW_SHA') == revision,
                'workflow requires the exact main dispatch/workflow SHA in ' + REPOSITORY)
    else:
        require(mode == 'local' and environment.get('GITHUB_ACTIONS') != 'true',
                'explicit local mode is unavailable inside GitHub Actions')
    return {'mode': mode, 'revision': revision,
            'scope': 'maintainer request; no review, full-CI, device or install attestation'}


def build_environment(environment, selected):
    require(not any(environment.get(name) for name in HOOKS),
            'Node hooks and emulator recipe overrides are unsupported')
    # Preserve proxy/CA trust, SDK/toolchain selectors and supported loader paths.
    # No caller feature override or workflow credential reaches source programs.
    result = {k: v for k, v in environment.items()
              if not k.startswith(('FELUCCA_', 'GITHUB_', 'ACTIONS_')) and
              k not in ('GH_TOKEN', 'GH_ENTERPRISE_TOKEN', 'GIT_ASKPASS', 'SSH_ASKPASS',
                        'EM_FROZEN_CACHE', 'GOLDEN_UPDATE', 'BUDGET_UPDATE')}
    result.update(FELUCCA_PROFILE=selected, GITHUB_ACTIONS='false',
                  PYTHONDONTWRITEBYTECODE='1')
    return result


def clean_source(root, revision):
    require(git(root, 'rev-parse', '--show-toplevel') == str(root), 'source must be a Git checkout root')
    require(git(root, 'rev-parse', 'HEAD') == revision, 'requested revision differs from clean current HEAD')
    require(not git(root, 'status', '--porcelain', '--untracked-files=all'), 'source checkout is dirty')
    require(build_manifest.REV.fullmatch(revision) is not None, 'unsupported revision')
    from build_identity import repository
    require(repository(root, env={}) == REPOSITORY, 'source origin must identify ' + REPOSITORY)
    engine = root / 'firmware/engines'
    require(git(engine, 'rev-parse', '--show-toplevel') == str(engine), 'Engines checkout is missing')
    require(git(engine, 'rev-parse', 'HEAD') == git(root, 'rev-parse', revision + ':firmware/engines'),
            'Engines checkout differs from the source gitlink')
    require(not git(engine, 'status', '--porcelain', '--untracked-files=all'), 'Engines checkout is dirty')


def output_path(root, output):
    path = Path(os.path.abspath(output))
    require(path.is_relative_to(root / 'build') and path != root / 'build',
            'output must be a new directory below this checkout build/')
    for parent in [path, *path.parents]:
        if parent == root:
            break
        require(not parent.is_symlink(), 'output path contains a symlink')
    require(not path.exists(), 'output already exists; choose a new run directory')
    return path


def plan(root, revision, selected, mode, output, environment):
    root = Path(root).resolve()
    require(selected in PROFILES, 'unsupported canonical profile')
    context = admission(mode, revision, environment)
    build_environment(environment, selected)
    clean_source(root, revision)
    profile.validate_selection(root, selected)
    version = re.search(r'^#define FELUCCA_VERSION "v([0-9]\.[0-9](?:\.[0-9]){0,2})(?:-[A-Za-z0-9]+)?"',
                        (root / 'firmware/src/felucca.c').read_text(), re.M)
    require(version is not None, 'source version cannot label a supported complete-source archive')
    return {'schema_version': 1, 'kind': 'felucca-maintainer-bundle-run',
            'source_root': str(root), 'revision': revision, 'profile': selected,
            'archive_label': version[1] + '-bundle',
            'admission': context, 'output': str(output_path(root, output)),
            'runtime': 'required', 'status': 'planned'}


def run_command(name, argv, cwd, environment, log):
    # argv is always a list from the trusted recipe, never shell-interpolated input.
    with log.open('wb') as stream:
        result = subprocess.run([str(a) for a in argv], cwd=cwd, env=environment,
                                stdout=stream, stderr=subprocess.STDOUT, timeout=1800)
    require(result.returncode == 0, name + ' failed; see ' + str(log))


def accepted_bundle(bundle, revision, selected):
    manifest = build_manifest.verify(bundle)
    identity = manifest['identity']
    require(identity['source']['repository'] == REPOSITORY and
            identity['source']['revision'] == revision and identity['profile']['name'] == selected,
            'verified bundle differs from the maintainer request')
    require(manifest['runtime']['state'] == 'available' and identity['runtime']['requested'],
            'this workflow requires a verified matching simulator')
    return manifest


def execute(request, environment, runner=run_command):
    root, output = Path(request['source_root']), Path(request['output'])
    # Revalidate admission and all source/output preconditions at execution time.
    fresh = plan(root, request['revision'], request['profile'], request['admission']['mode'], output, environment)
    require(fresh == request, 'request changed after planning')
    env = build_environment(environment, request['profile'])
    output.mkdir(parents=True, exist_ok=False)
    logs = output / 'logs'; logs.mkdir()
    source = output / 'source'
    engine = source / 'firmware/engines'
    archive = output / ('felucca-' + request['archive_label'] + '-source.tar.gz')
    reproduced = output / 'extracted' / ('felucca-' + request['archive_label'] + '-source')
    candidate, destination = output / 'candidate-bundle', output / 'verified-bundle'
    result = dict(request, status='running', commands=[])

    def save():
        (output / 'RESULT.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')

    def command(name, argv, cwd):
        row = {'name': name, 'argv': list(map(str, argv)), 'cwd': str(cwd), 'state': 'running'}
        result['commands'].append(row); save()
        try:
            runner(name, row['argv'], cwd, env, logs / (name + '.log'))
            row['state'] = 'passed'
        except BaseException:
            row['state'] = 'failed'
            raise
        finally:
            save()

    try:
        command('clone-source', ['git', 'clone', '--no-local', '--no-checkout', '--', root, source], root)
        command('checkout-source', ['git', 'checkout', '--detach', request['revision']], source)
        command('source-origin', ['git', 'remote', 'set-url', 'origin', git(root, 'remote', 'get-url', 'origin')], source)
        command('engine-registration', ['git', 'submodule', 'init', '--', 'firmware/engines'], source)
        command('clone-engines', ['git', 'clone', '--no-local', '--no-checkout', '--', root / 'firmware/engines', engine], root)
        command('checkout-engines', ['git', 'checkout', '--detach', git(root, 'rev-parse', request['revision'] + ':firmware/engines')], engine)
        clean_source(source, request['revision'])
        command('native-build', ['sh', 'build.sh'], source)
        command('source-export', [sys.executable, 'tools/source_archive.py', 'export', request['archive_label'],
                                 '--output', archive], source)
        metadata = source_archive.verify_archive(archive)
        require(metadata['firmware_revision'] == request['revision'], 'exported revision differs from request')
        # The existing verifier rejects aliases, links and malformed members before extraction.
        with tarfile.open(archive, 'r:gz') as stream:
            stream.extractall(output / 'extracted', filter='data')
        source_archive.verify_tree(reproduced)
        command('git-free-build', ['sh', 'build.sh'], reproduced)
        # Populate the installed SDK's normal no-ports sysroot before the paired
        # producer freezes it. This first output is never accepted as a match.
        command('runtime-prepare', ['sh', 'web/emu/build.sh'], source)
        command('paired-runtime', ['sh', 'web/emu/build.sh', '--target-report', 'build/resource-report.json'], source)
        command('seal', [sys.executable, 'tools/build_manifest.py', 'create', '--root', source,
                        '--allow-revision', request['revision'], '--profile', request['profile'],
                        '--source-archive', archive, '--reproduction-root', reproduced,
                        '--runtime-receipt', source / 'build/emu/runtime-report.json', '--out', candidate], source)
        manifest = accepted_bundle(candidate, request['revision'], request['profile'])
        clean_source(root, request['revision'])
        clean_source(source, request['revision'])
        candidate.rename(destination)
        result.update(status='verified', configuration_key=manifest['configuration_key'],
                      manifest_sha256=build_manifest.digest(destination / 'manifest.json'), bundle=str(destination))
        save()
        return result
    except BaseException as error:
        result.update(status='failed', error=type(error).__name__ + ': ' + str(error))
        save()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('plan', 'run'))
    parser.add_argument('--mode', choices=('workflow', 'local'), required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--profile', choices=PROFILES, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        request = plan(Path(__file__).resolve().parents[1], args.revision, args.profile,
                       args.mode, args.output, os.environ)
        result = request if args.command == 'plan' else execute(request, os.environ)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError, tarfile.TarError, KeyError, TypeError) as error:
        parser.exit(2, 'maintainer bundle: ' + str(error) + '\n')


if __name__ == '__main__':
    sys.exit(main())
