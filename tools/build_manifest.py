#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Seal and verify a maintainer-only build bundle; no publication or installation."""
# Verified archives must not execute cached helpers before checking their source tree.
# os/sys are loaded by Python startup; defer all repository and other stdlib imports.
import os as _source_os
import sys as _source_sys

_source_root = _source_os.path.dirname(_source_os.path.dirname(_source_os.path.realpath(__file__)))
_source_verifier = None
if _source_os.path.isfile(_source_os.path.join(_source_root, "SOURCE-PINS.json")):
    _source_sys.dont_write_bytecode = True
    _source_os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    _source_import_paths = _source_sys.path[:]
    try:
        # The verifier uses only stdlib. Exclude archive paths while loading it,
        # so an unmanifested module cannot shadow a stdlib dependency either.
        _source_sys.path = [p for p in _source_import_paths
                            if not (_source_os.path.realpath(p or _source_os.getcwd()) == _source_root
                                    or _source_os.path.realpath(p or _source_os.getcwd()).startswith(_source_root + _source_os.sep))]
        _source_verifier_path = _source_os.path.join(_source_root, "tools", "source_archive.py")
        _source_verifier = {"__name__": "felucca_source_verifier", "__file__": _source_verifier_path}
        with open(_source_verifier_path, "rb") as _source_verifier_file:
            exec(compile(_source_verifier_file.read(), _source_verifier_path, "exec"), _source_verifier)
        _source_verifier["verify_tree"](_source_root)
    except (OSError, ValueError) as _source_error:
        raise SystemExit(str(_source_error))
    finally:
        _source_sys.path = _source_import_paths


import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

import build_report
import fm1_install
import profile
import source_archive

KIND = 'felucca-build-manifest'
SCOPE = 'maintainer-only staging; no publication/install approval or compatibility guarantee'
BROADER_ACCEPTANCE = {'host': 'not_evaluated', 'browser': 'not_evaluated', 'physical': 'not_performed'}
SHA = re.compile(r'[0-9a-f]{64}')
REV = re.compile(r'[0-9a-f]{40}')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode('utf-8')


def digest(path):
    return build_report.digest(Path(path))


def read_json(path):
    value = profile.read_json(Path(path))
    canonical(value)  # Reject NaN/Infinity before using any bound evidence.
    return value


def require(ok, message):
    if not ok:
        raise ValueError(message)


def keys(value, expected, label):
    require(isinstance(value, dict) and set(value) == set(expected), 'invalid ' + label)


def safe_path(name):
    require(isinstance(name, str) and bool(re.fullmatch(r'[A-Za-z0-9_./-]+', name)), 'unsafe bundle path')
    path = PurePosixPath(name)
    require(name not in ('.', '..') and not path.is_absolute() and path.as_posix() == name and
            all(part not in ('.', '..', '.git') for part in path.parts), 'unsafe bundle path: ' + name)
    return path


def file_at(root, name):
    path = root / safe_path(name)
    parent = path
    while parent != root:
        require(not parent.is_symlink(), 'bundle path is a symlink: ' + name)
        parent = parent.parent
    require(path.is_file(), 'missing bundle file: ' + name)
    return path


def record(path):
    return {'sha256': digest(path), 'bytes': path.stat().st_size}


def archive_metadata(path):
    metadata = source_archive.verify_archive(path)
    marker = f"felucca-{metadata['version']}-source/SOURCE-PINS.json"
    with tarfile.open(path, 'r:gz') as archive:
        marker_hash = hashlib.sha256(archive.extractfile(marker).read()).hexdigest()
    return metadata, marker_hash


def validate_report(root, report, metadata, marker_hash):
    require(isinstance(report, dict) and type(report.get('schema_version')) is int and
            report.get('schema_version') == 1 and report.get('kind') == 'felucca-post-link-resource-report'
            and report.get('validation') == 'production build guards passed', 'unsupported native report')
    require(metadata['engines'].get('license') == 'MIT' and
            not any(p.startswith('firmware/engines-gpl/') for p in metadata['files']), 'GPL collection is not supported by this bundle schema')
    identity = report.get('build_identity', {})
    require(identity.get('revision') == metadata['firmware_revision'] and identity.get('dirty') is False and
            identity.get('repository') == metadata['repository'] == 'kmplngj/Felucca', 'native source identity mismatch')
    require(identity.get('source') in ('git', 'verified archive'), 'unidentified native source')
    configuration = report.get('configuration')
    require(isinstance(configuration, dict) and
            hashlib.sha256(build_report.canonical(configuration)).hexdigest() == report.get('configuration_sha256'),
            'native configuration digest mismatch')
    require(isinstance(configuration.get('logical_constants'), dict), 'missing native logical constants')
    execution = configuration.get('execution_environment')
    keys(execution, ('backend', 'image_reference', 'system_runtime_fingerprint'), 'execution environment scope')
    require(execution['backend'] in ('native', 'docker') and execution['system_runtime_fingerprint'] is None,
            'unsupported execution environment claim')
    generators = configuration.get('generator_runtime', {})
    keys(generators, ('python', 'Pillow', 'fontTools', 'Brotli', 'raqm', 'freetype', 'lock_sha256'), 'generator runtime')
    require(all(isinstance(generators[k], str) and generators[k] for k in ('python', 'Pillow', 'fontTools', 'Brotli'))
            and SHA.fullmatch(generators.get('lock_sha256') or '') is not None, 'missing build-time generator provenance')
    inputs = report.get('input_sha256')
    require(isinstance(inputs, dict) and inputs and
            hashlib.sha256(build_report.canonical(inputs)).hexdigest() == report.get('inputs_sha256'),
            'native input digest mismatch')
    expected = {name: item['sha256'] for name, item in metadata['files'].items()}
    generated = {}
    for name, value in inputs.items():
        require(isinstance(value, str) and SHA.fullmatch(value) is not None, 'invalid native input digest')
        if name.startswith('build/gen/') and Path(name).suffix in ('.h', '.inc', '.json'):
            safe_path(name)
            generated[name] = value
        elif name == 'SOURCE-PINS.json':
            require(identity['source'] == 'verified archive' and value == marker_hash, 'source marker mismatch')
        else:
            source_archive.safe_path(name)
            require(expected.get(name) == value, 'archive/native source mismatch: ' + name)
    source_names = set(inputs) - set(generated) - {'SOURCE-PINS.json'}
    require(source_names == set(expected) and generated, 'incomplete archive/native source inventory')
    require(('SOURCE-PINS.json' in inputs) == (identity['source'] == 'verified archive'), 'source marker origin mismatch')
    require(isinstance(report.get('package'), str), 'invalid native package name')
    headers = configuration.get('compiler_headers_sha256')
    require(isinstance(headers, dict) and headers and any(p.endswith('/stdint.h') for p in headers),
            'missing compiler header provenance')
    declared = report.get('artifact_sha256')
    require(isinstance(declared, dict) and set(declared) == set(build_report.artifact_paths(report.get('package'))),
            'incomplete native artifact set')
    for name, value in {**generated, **declared}.items():
        require(isinstance(value, str) and SHA.fullmatch(value) is not None and
                digest(file_at(root, name)) == value, 'native artifact mismatch: ' + name)
    require(read_json(file_at(root, 'build/gen/build-identity.json')) == identity, 'native identity artifact mismatch')
    resolved = read_json(file_at(root, 'build/gen/resolved-profile.json'))
    contract = read_json(file_at(root, 'build/profile-contract.json'))
    name = resolved.get('profile')
    require(name in profile.SUPPORTED_PROFILES and name in contract.get('supported_profiles', {}), 'unsupported canonical profile')
    require(resolved.get('asset_variant') == 'm8stealth' and resolved.get('build_flags') ==
            {'FELUCCA_FM4': '0', 'FELUCCA_SLICE': '1'}, 'noncanonical profile features')
    pins = resolved.get('source_pins', {})
    require(pins.get('firmware_revision') == metadata['firmware_revision'] and
            pins.get('engines_gitlink') == metadata['engines']['revision'] and
            all(contract.get('source_pins', {}).get(k) == pins.get(k) for k in
                ('firmware_revision', 'engines_gitlink')) and
            contract['supported_profiles'][name].get('resolved') == resolved, 'native profile source mismatch')
    require(read_json(file_at(root, 'build/felucca.dis.profile.json')).get('resolved_profile') == resolved,
            'native disassembly profile mismatch')
    flags = configuration.get('effective_defines', {})
    require(flags.get('FELUCCA_ENG_TEST14') == '0' and flags.get('FELUCCA_ENG_OMIT') == '(-1)' and
            flags.get('FELUCCA_FM4') == '0' and flags.get('FELUCCA_SLICE') == '1', 'nonproduction engine overrides')
    for name, value in resolved.get('input_sha256', {}).items():
        require(inputs.get(name) == value, 'profile input mismatch: ' + name)
    return resolved, contract, generated


def input_identity(report, resolved, metadata, generated, runtime_configuration, requested):
    key_metadata = {'state': 'unavailable', 'reason': 'producer_does_not_export_keys'}
    if 'engine_identity_reference' in resolved or 'engine_identities' in resolved:
        reference = resolved.get('engine_identity_reference', {})
        require(metadata['files'].get(reference.get('path'), {}).get('sha256') == reference.get('sha256')
                and isinstance(resolved.get('engine_identities'), list), 'engine identity reference mismatch')
        key_metadata = {'state': 'available', 'reference': reference, 'selected': resolved['engine_identities']}
    return {'source': {'repository': metadata['repository'], 'revision': metadata['firmware_revision'],
                       'committed_files_sha256': hashlib.sha256(canonical(metadata['files'])).hexdigest(),
                       'archive_label': metadata['version'], 'engines': metadata['engines'], 'gpl': 'not_consumed'},
            'profile': {'name': resolved['profile'], 'asset_variant': resolved['asset_variant'],
                        'selection_sha256': resolved['selection_sha256'],
                        'resolved_profile_sha256': report['artifact_sha256']['build/gen/resolved-profile.json'],
                        'profile_contract_sha256': report['artifact_sha256']['build/profile-contract.json'],
                        'generator_input_sha256': resolved['input_sha256'],
                        'generated_c_input_sha256': {p: h for p, h in generated.items() if Path(p).suffix in ('.h', '.inc')},
                        'engine_key_metadata': key_metadata},
            'target': report['configuration'],
            'runtime': {'requested': requested, 'configuration': runtime_configuration},
            'client': {'state': 'not_included'}}


def runtime_identity(root, path, report, report_hash):
    import wasm_report
    receipt = read_json(file_at(root, path))
    configuration = wasm_report.verify_receipt(root, receipt, report, target_report_sha256=report_hash)
    return configuration, receipt


def source_identity(metadata):
    return {'repository': metadata['repository'], 'revision': metadata['firmware_revision'],
            'committed_files_sha256': hashlib.sha256(canonical(metadata['files'])).hexdigest(),
            'engines_revision': metadata['engines']['revision']}


def license_paths(metadata):
    return sorted({'LICENSE', 'LICENSING.md', 'assets/samples-cc0/ATTRIBUTION.txt'} |
                  {p for p in metadata['files'] if p.startswith('LICENSES/') and p.endswith('.txt')})


def reproduction_record(metadata, archive, native_report, native_hash, reproduced, reproduced_hash):
    return {'schema_version': 1, 'kind': 'felucca-source-reproduction',
            'archive_sha256': digest(archive), 'source': source_identity(metadata),
            'native_report_sha256': native_hash, 'reproduced_report_sha256': reproduced_hash,
            'app_sha256': native_report['artifact_sha256']['build/felucca.bin'],
            'package_sha256': native_report['artifact_sha256']['build/' + native_report['package']],
            'configuration_sha256': native_report['configuration_sha256'],
            'resources_sha256': hashlib.sha256(canonical(native_report['resources'])).hexdigest(),
            'stack_reservations_sha256': hashlib.sha256(canonical(native_report['stack_reservations'])).hexdigest(),
            'origins': [native_report['build_identity']['source'], reproduced['build_identity']['source']]}


def verify_reproduction(root, artifacts, metadata, marker_hash, native_report):
    path = 'reproduction/build/resource-report.json'
    reproduced = read_json(file_at(root, path))
    validate_report(root / 'reproduction', reproduced, metadata, marker_hash)
    require(reproduced['build_identity']['source'] == 'verified archive', 'reproduction did not use Git-free sources')
    require(native_report['package'] == reproduced['package'] and
            native_report['configuration'] == reproduced['configuration'] and
            native_report['resources'] == reproduced['resources'] and
            native_report['stack_reservations'] == reproduced['stack_reservations'], 'reproduction configuration/resources differ')
    for name in ('build/felucca.bin', 'build/' + native_report['package']):
        require(native_report['artifact_sha256'][name] == reproduced['artifact_sha256'][name],
                'reproduction output differs: ' + name)
    expected = reproduction_record(metadata, root / artifacts['source_archive'], native_report,
                                  digest(root / artifacts['native_report']), reproduced, digest(root / path))
    require(read_json(file_at(root, 'checks/source_reproduction.json')) == expected, 'reproduction receipt is for another build')


def checksum_text(files, manifest_hash):
    rows = {**{name: value['sha256'] for name, value in files.items()}, 'manifest.json': manifest_hash}
    return ''.join(f'{rows[name]}  {name}\n' for name in sorted(rows))


def verify(bundle):
    """Check sealed byte/evidence relationships offline; never claim new compiler/device validation."""
    root = Path(bundle).resolve()
    require(root.is_dir(), 'missing bundle directory')
    manifest_path = file_at(root, 'manifest.json')
    manifest = read_json(manifest_path)
    keys(manifest, ('schema_version', 'kind', 'configuration_key', 'identity', 'artifacts', 'runtime', 'checks',
                    'broader_acceptance', 'scope', 'files'), 'manifest')
    require(type(manifest['schema_version']) is int and manifest['schema_version'] == 1 and
            manifest['kind'] == KIND and manifest['scope'] == SCOPE, 'unsupported build manifest')
    require(manifest['broader_acceptance'] == BROADER_ACCEPTANCE, 'bundle cannot declare broader acceptance')
    require(manifest_path.read_bytes() == canonical(manifest) + b'\n', 'noncanonical manifest bytes')
    files = manifest['files']
    require(isinstance(files, dict) and files and not {'manifest.json', 'SHA256SUMS'} & files.keys(), 'invalid bundle inventory')
    require(len({name.casefold() for name in [*files, 'manifest.json', 'SHA256SUMS']}) == len(files) + 2,
            'case-colliding bundle files')
    for name, expected in files.items():
        keys(expected, ('sha256', 'bytes'), 'file record')
        require(isinstance(expected['sha256'], str) and SHA.fullmatch(expected['sha256']) is not None and
                type(expected['bytes']) is int and expected['bytes'] >= 0, 'invalid file fingerprint')
        require(record(file_at(root, name)) == expected, 'bundle file mismatch: ' + name)
    actual = set()
    for path in root.rglob('*'):
        require(not path.is_symlink(), 'symlink in bundle')
        if path.is_file(): actual.add(path.relative_to(root).as_posix())
    require(actual == set(files) | {'manifest.json', 'SHA256SUMS'}, 'undeclared or missing bundle files')
    require(file_at(root, 'SHA256SUMS').read_text() == checksum_text(files, digest(manifest_path)), 'invalid detached checksums')
    artifacts = manifest['artifacts']
    keys(artifacts, ('native_report', 'native_declared', 'generated', 'source_archive', 'source_pins_sha256', 'licenses', 'evidence'), 'artifact roles')
    roles = [artifacts['native_report'], artifacts['source_archive'], *artifacts['native_declared'],
             *artifacts['generated'], *artifacts['licenses'], *artifacts['evidence']]
    require(all(isinstance(name, str) and name in files for name in roles), 'missing artifact role')
    metadata, marker_hash = archive_metadata(file_at(root, artifacts['source_archive']))
    require(marker_hash == artifacts['source_pins_sha256'], 'source pin manifest mismatch')
    report = read_json(file_at(root, artifacts['native_report']))
    resolved, contract, generated = validate_report(root, report, metadata, marker_hash)
    require(artifacts['native_report'] == 'build/resource-report.json' and
            artifacts['native_declared'] == sorted(report['artifact_sha256']) and
            artifacts['generated'] == sorted(generated), 'native artifact roles differ from report')
    require(artifacts['licenses'] == license_paths(metadata), 'incomplete license inventory')
    for name in artifacts['licenses']:
        require(digest(root / name) == metadata['files'][name]['sha256'], 'license differs from source archive')
    # Offline package validation is structural/CRC, not device acceptance.
    product, _ = fm1_install.load_package(file_at(root, 'build/' + report['package']), False)
    require(product == report['configuration']['product'], 'package product differs from native configuration')
    verify_reproduction(root, artifacts, metadata, marker_hash, report)
    runtime = manifest['runtime']
    configuration = None
    if runtime.get('state') == 'available':
        keys(runtime, ('state', 'receipt', 'files'), 'available runtime')
        configuration, receipt = runtime_identity(root, runtime['receipt'], report, digest(root / artifacts['native_report']))
        require(receipt['source'] == source_identity(metadata), 'runtime source differs from source archive')
        require(runtime['files'] == sorted(item['path'] for item in receipt['files']) and
                all(name in files for name in [runtime['receipt'], *runtime['files']]), 'runtime artifact roles mismatch')
        roles += [runtime['receipt'], *runtime['files']]
    else:
        keys(runtime, ('state', 'reason'), 'unavailable runtime')
        require(runtime['state'] == 'unavailable' and runtime['reason'] in
                ('not_requested', 'build_failed', 'provenance_missing'), 'invalid unavailable runtime')
    checks = manifest['checks']
    required = ('native_report', 'target_budget', 'package_integrity', 'source_archive', 'source_reproduction')
    keys(checks, required, 'native checks')
    for check in checks.values():
        keys(check, ('state', 'command', 'exit_code', 'evidence'), 'check receipt')
        require(check['state'] == 'passed' and type(check['exit_code']) is int and check['exit_code'] == 0 and isinstance(check['command'], list) and
                check['command'] and isinstance(check['evidence'], list) and check['evidence'] and
                all(p in artifacts['evidence'] for p in check['evidence']), 'missing passed native evidence')
    for label, check in checks.items():
        result_name = 'checks/' + label + '.result.json'
        require(result_name in check['evidence'], 'missing structured check result')
        result = read_json(file_at(root, result_name))
        expected = check_record(label, check, root, digest(root / artifacts['native_report']),
                                digest(root / artifacts['source_archive']))
        require(result == expected, 'check receipt is for another build: ' + label)
    expected_identity = input_identity(report, resolved, metadata, generated, configuration,
                                       runtime['state'] == 'available' or runtime.get('reason') != 'not_requested')
    require(manifest['identity'] == expected_identity and manifest['configuration_key'] ==
            hashlib.sha256(b'felucca-build-key-v1\0' + canonical(expected_identity)).hexdigest(), 'build configuration key mismatch')
    require(set(roles) == set(files), 'unassigned bundle payload')
    return manifest


def run_check(command, cwd, destination, env=None):
    """The external-process seam; command and actual result stay in the sealed evidence."""
    with destination.open('wb') as output:
        process = subprocess.run(command, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT)
    require(process.returncode == 0, f'check failed ({process.returncode}): {command}; log {destination}')
    return command


def check_record(label, check, root, report_hash, archive_hash):
    result_name = 'checks/' + label + '.result.json'
    return {'schema_version': 1, 'kind': 'felucca-build-check', 'check': label,
            'native_report_sha256': report_hash, 'source_archive_sha256': archive_hash,
            'command': check['command'], 'exit_code': check['exit_code'],
            'evidence_sha256': {p: digest(file_at(root, p)) for p in check['evidence'] if p != result_name}}


def create(root, archive, reproduction_root, destination, *, allowed_revision, profile_name,
           runtime_receipt=None, runtime_unavailable='not_requested', evidence=()):
    require(not Path(destination).is_symlink(), 'bundle destination is a symlink')
    root, archive, reproduction_root, destination = map(lambda p: Path(p).resolve(),
                                                       (root, archive, reproduction_root, destination))
    require(isinstance(allowed_revision, str) and REV.fullmatch(allowed_revision) is not None, 'allow one full immutable revision')
    require(profile_name in profile.SUPPORTED_PROFILES, 'unsupported canonical profile')
    metadata, marker_hash = archive_metadata(archive)
    require(metadata['firmware_revision'] == allowed_revision, 'source revision is not allowlisted')
    require(not (reproduction_root / '.git').exists() and (reproduction_root / 'SOURCE-PINS.json').is_file(),
            'source reproduction must be a verified Git-free extraction')
    require(source_archive.verify_tree(reproduction_root) == metadata, 'reproduction source differs from archive')
    report_path = file_at(root, 'build/resource-report.json')
    report = read_json(report_path)
    resolved, contract, generated = validate_report(root, report, metadata, marker_hash)
    require(resolved['profile'] == profile_name, 'selected profile differs from native report')
    require(build_report.input_hashes(root) == report['input_sha256'], 'source changed after native build')
    # Match the actual source origin; metadata alone cannot describe a dirty checkout.
    from build_identity import resolve
    require(resolve(root, report['configuration']['version_override']) == report['build_identity'], 'current source identity differs from build')
    require(runtime_unavailable in ('not_requested', 'build_failed', 'provenance_missing'), 'unknown runtime failure reason')
    configuration = receipt = None
    runtime_name = None
    if runtime_receipt is not None:
        require(runtime_unavailable == 'not_requested', 'conflicting runtime arguments')
        runtime_name = Path(runtime_receipt).resolve().relative_to(root).as_posix()
        configuration, receipt = runtime_identity(root, runtime_name, report, digest(report_path))
        require(receipt['source'] == source_identity(metadata), 'runtime source differs from source archive')
    destination.parent.mkdir(parents=True, exist_ok=True)
    lock_path = destination.with_name('.' + destination.name + '.seal-lock')
    descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    temporary = None
    try:
        temporary = Path(tempfile.mkdtemp(prefix='.' + destination.name + '.staging-', dir=destination.parent))
        (temporary / 'checks').mkdir()
        checks = {}
        environment = dict(os.environ, FELUCCA_PROFILE=profile_name)
        for label, command, cwd in (
            ('native_report', [sys.executable, str(root / 'tools/build_report.py'), '--verify', 'build/resource-report.json'], root),
            ('target_budget', [sys.executable, str(root / 'tests/target_budget.py'), 'build/felucca.dis', 'tests/target_budget.txt'], root),
            ('source_archive', [sys.executable, str(root / 'tools/source_archive.py'), 'verify', str(archive)], root),
            ('source_reproduction', [sys.executable, str(reproduction_root / 'tools/build_report.py'), '--verify', 'build/resource-report.json'], reproduction_root)):
            log = 'checks/' + label + '.log'
            run_check(command, cwd, temporary / log, environment)
            checks[label] = dict(state='passed', command=command, exit_code=0, evidence=[log])
        product, _ = fm1_install.load_package(root / 'build' / report['package'], False)
        require(product == report['configuration']['product'], 'package product differs from native configuration')
        package_log = 'checks/package_integrity.json'
        (temporary / package_log).write_bytes(canonical({'package': report['package'], 'sha256': digest(root / 'build' / report['package']),
                                                       'method': 'fm1_install.load_package(force=False)'}) + b'\n')
        checks['package_integrity'] = dict(state='passed', command=['fm1_install.load_package'], exit_code=0, evidence=[package_log])
        reproduced = read_json(file_at(reproduction_root, 'build/resource-report.json'))
        validate_report(reproduction_root, reproduced, metadata, marker_hash)
        require(report['configuration'] == reproduced['configuration'] and
                report['resources'] == reproduced['resources'] and report['stack_reservations'] == reproduced['stack_reservations'],
                'source reproduction configuration/resources differ')
        for name in ('build/felucca.bin', 'build/' + report['package']):
            require(digest(file_at(root, name)) == digest(file_at(reproduction_root, name)), 'source reproduction differs: ' + name)
        reproduction_log = 'checks/source_reproduction.json'
        (temporary / reproduction_log).write_bytes(canonical(reproduction_record(metadata, archive, report,
            digest(report_path), reproduced, digest(reproduction_root / 'build/resource-report.json'))) + b'\n')
        checks['source_reproduction']['evidence'].append(reproduction_log)
        reproduced_names = set(reproduced['artifact_sha256']) | {
            p for p in reproduced['input_sha256'] if p.startswith('build/gen/')} | {'build/resource-report.json'}
        for name in sorted(reproduced_names):
            target = temporary / 'reproduction' / safe_path(name); target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file_at(reproduction_root, name), target)
        for label, check in checks.items():
            result_name = 'checks/' + label + '.result.json'
            (temporary / result_name).write_bytes(canonical(check_record(label, check, temporary,
                digest(report_path), digest(archive))) + b'\n')
            check['evidence'].append(result_name)
        names = set(report['artifact_sha256']) | set(generated) | {'build/resource-report.json'}
        licenses = license_paths(metadata)
        names.update(licenses)
        if receipt is not None:
            names.update(item['path'] for item in receipt['files']); names.add(runtime_name)
        for name in sorted(names):
            target = temporary / safe_path(name); target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file_at(root, name), target)
        for index, path in enumerate(map(Path, evidence)):
            require(path.is_file() and not path.is_symlink(), 'missing/linked evidence copy')
            target = temporary / safe_path('evidence/' + str(index) + '-' + path.name)
            target.parent.mkdir(exist_ok=True); shutil.copyfile(path, target)
        archive_name = 'source/' + archive.name
        (temporary / 'source').mkdir(); shutil.copyfile(archive, temporary / archive_name)
        if build_report.input_hashes(root) != report['input_sha256']:
            raise ValueError('source changed while sealing bundle')
        files = {p.relative_to(temporary).as_posix(): record(p) for p in sorted(temporary.rglob('*')) if p.is_file()}
        identity = input_identity(report, resolved, metadata, generated, configuration,
                                  receipt is not None or runtime_unavailable != 'not_requested')
        manifest = dict(schema_version=1, kind=KIND, configuration_key=hashlib.sha256(b'felucca-build-key-v1\0' + canonical(identity)).hexdigest(),
            identity=identity, artifacts=dict(native_report='build/resource-report.json', native_declared=sorted(report['artifact_sha256']),
                generated=sorted(generated), source_archive=archive_name, source_pins_sha256=marker_hash, licenses=licenses,
                evidence=sorted(p for p in files if p.startswith(('checks/', 'reproduction/', 'evidence/')))),
            runtime=(dict(state='available', receipt=runtime_name, files=sorted(item['path'] for item in receipt['files']))
                     if receipt is not None else dict(state='unavailable', reason=runtime_unavailable)),
            checks=checks, broader_acceptance=dict(BROADER_ACCEPTANCE), scope=SCOPE, files=files)
        (temporary / 'manifest.json').write_bytes(canonical(manifest) + b'\n')
        (temporary / 'SHA256SUMS').write_text(checksum_text(files, digest(temporary / 'manifest.json')))
        verify(temporary)
        if destination.exists() or destination.is_symlink():
            require(not destination.is_symlink() and verify(destination) == manifest, 'existing bundle differs; refusing overwrite')
            shutil.rmtree(temporary)
        else:
            temporary.rename(destination)
        return manifest
    except BaseException:
        if temporary is not None and temporary.exists():
            failed = temporary.with_name(temporary.name.replace('.staging-', '.failed-'))
            temporary.rename(failed)
        raise
    finally:
        try:
            os.close(descriptor)
        finally:
            lock_path.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    creator = commands.add_parser('create')
    creator.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    creator.add_argument('--source-archive', type=Path, required=True)
    creator.add_argument('--reproduction-root', type=Path, required=True)
    creator.add_argument('--out', type=Path, required=True)
    creator.add_argument('--allow-revision', required=True)
    creator.add_argument('--profile', choices=profile.SUPPORTED_PROFILES, required=True)
    creator.add_argument('--runtime-receipt', type=Path)
    creator.add_argument('--runtime-unavailable', choices=('not_requested', 'build_failed', 'provenance_missing'), default='not_requested')
    creator.add_argument('--evidence', type=Path, action='append', default=[], help='copy exact additional receipts; outcomes are not inferred')
    checker = commands.add_parser('verify'); checker.add_argument('bundle', type=Path)
    args = parser.parse_args()
    try:
        result = (verify(args.bundle) if args.command == 'verify' else create(args.root, args.source_archive,
            args.reproduction_root, args.out, allowed_revision=args.allow_revision, profile_name=args.profile,
            runtime_receipt=args.runtime_receipt, runtime_unavailable=args.runtime_unavailable, evidence=args.evidence))
        print('build bundle: verified ' + result['configuration_key'])
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, fm1_install.InstallError) as error:
        parser.exit(2, 'error: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
