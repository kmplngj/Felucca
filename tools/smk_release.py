#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Seal and stage experimental SMK assets; never publish or approve hardware testing."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

import build_manifest as manifest
import build_report
import ci
import fm1_install
import fm1pkg_make
import source_archive

KIND = 'felucca-experimental-smk-release'
REPORT = 'build/resource-report.json'
MANIFEST = 'SMK-RELEASE.json'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    return manifest.read_json(path)


def digest(path):
    return build_report.digest(path)


def names(version, model):
    ci.version(version)
    fm1pkg_make.target('smk37', model)
    stem = f'felucca-{version}-smk37' + ('-' + model if model != 'pro' else '')
    return stem, stem + '.fwsc', fm1pkg_make.MODELS[model] + '_9' + version[0] + version[2]


def target_report(report, version, model, revision, source):
    stem, package, product = names(version, model)
    identity, config = report['build_identity'], report['configuration']
    require(identity.get('revision') == revision and identity.get('dirty') is False
            and identity.get('source') == source and identity.get('version') == 'v' + version.lower()
            and identity.get('version_source') == 'override' and identity.get('pr') is None,
            'SMK release source/version identity mismatch')
    require(report.get('package') == package and config.get('board') == 'smk37'
            and config.get('model') == model and config.get('product') == product
            and config.get('version_override') == 'v' + version.lower(), 'SMK release target mismatch')
    defines = config['effective_defines']
    require(defines.get('BOARD_SMK37') == '1' and defines.get('SMK_MODEL') == '"' + fm1pkg_make.MODELS[model] + '"'
            and defines.get('FELUCCA_ID') == '"' + product + '"' and defines.get('FELUCCA_UART') == '0',
            'SMK release effective model/UART identity mismatch')
    require(all(defines.get(flag, '0') == '0' for flag in ci.build.DIAG_FLAGS), 'SMK release diagnostic build')
    require(hashlib.sha256(build_report.canonical(config)).hexdigest() == report['configuration_sha256'],
            'SMK release configuration checksum mismatch')
    return stem, package, product


def check_inputs(report, metadata, marker_hash):
    inputs = report['input_sha256']
    require(hashlib.sha256(build_report.canonical(inputs)).hexdigest() == report['inputs_sha256'],
            'SMK reproduction input checksum mismatch')
    source = {name: value for name, value in inputs.items() if not name.startswith('build/gen/')}
    require(source.pop('SOURCE-PINS.json', None) == marker_hash, 'SMK reproduction source manifest mismatch')
    require(source == {name: item['sha256'] for name, item in metadata['files'].items()},
            'SMK reproduction source inventory mismatch')


def verify(root, version, model, revision):
    """Read-only verification of an isolated CI model bundle, including every file checksum."""
    root = Path(root)
    require(not root.is_symlink(), 'SMK bundle is a symlink')
    data = read(manifest.file_at(root, MANIFEST))
    manifest.keys(data, ('schema_version', 'kind', 'version', 'model', 'revision', 'source_distribution',
                         'reproduction', 'files'), 'SMK release manifest')
    require(type(data['schema_version']) is int and data['schema_version'] == 1 and data['kind'] == KIND
            and (data['version'], data['model'], data['revision']) == (version, model, revision),
            'SMK release manifest identity mismatch')
    ci.verify_checksums(root)
    files = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    require(files == set(data['files']) | {MANIFEST, 'SHA256SUMS'}, 'SMK bundle file inventory mismatch')
    for name, sha in data['files'].items():
        require(digest(manifest.file_at(root, name)) == sha, 'SMK artifact checksum mismatch: ' + name)
    archive = manifest.file_at(root, data['source_distribution']['archive'])
    source_archive.verify_archive(archive, data['source_distribution'])
    metadata, marker_hash = manifest.archive_metadata(archive)
    require(metadata['version'] == version and metadata['firmware_revision'] == revision,
            'SMK archive version/revision mismatch')
    report = read(manifest.file_at(root, REPORT))
    stem, package, product = target_report(report, version, model, revision, 'git')
    resolved, contract, generated = manifest.validate_report(root, report, metadata, marker_hash)
    require(resolved.get('profile') == 'standard', 'SMK release requires standard engine profile')
    raw_path = manifest.file_at(root, 'build/' + package)
    actual, image = fm1_install.load_package(raw_path, False)
    require(actual == product and fm1_install.package_family(image, actual) == 'felucca-v1:' + fm1pkg_make.MODELS[model],
            'SMK release package model/layout/loader family mismatch')
    reproduced = read(manifest.file_at(root, 'reproduction-resource-report.json'))
    target_report(reproduced, version, model, revision, 'verified archive')
    check_inputs(reproduced, metadata, marker_hash)
    package_sha = digest(raw_path)
    require(reproduced['artifact_sha256'].get('build/' + package) == package_sha
            and data['reproduction'] == {'method': 'clean verified source archive',
                'package_sha256': package_sha, 'source_sha256': digest(archive)}, 'SMK package reproduction mismatch')
    require(digest(manifest.file_at(root, 'SMK37.md')) == metadata['files']['docs/smk37.md']['sha256'],
            'SMK guidance does not match pinned source')
    return data


def prepare(root, version, model, reproduction, destination):
    """Bundle checked native and clean-source outputs, retaining full resource evidence."""
    root, reproduction, destination = map(Path, (root, reproduction, destination))
    stem, package, product = names(version, model)
    require(not destination.exists(), 'SMK bundle destination already exists')
    destination.mkdir(parents=True)
    try:
        source = source_archive.export(root, destination / f'felucca-{version}-source.tar.gz', version)
        metadata, marker_hash = manifest.archive_metadata(destination / source['archive'])
        report = read(root / REPORT)
        target_report(report, version, model, metadata['firmware_revision'], 'git')
        resolved, contract, generated = manifest.validate_report(root, report, metadata, marker_hash)
        require(resolved.get('profile') == 'standard', 'SMK release requires standard engine profile')
        reproduced = read(reproduction / REPORT)
        target_report(reproduced, version, model, metadata['firmware_revision'], 'verified archive')
        manifest.validate_report(reproduction, reproduced, metadata, marker_hash)
        require(digest(root / 'build' / package) == digest(reproduction / 'build' / package),
                'SMK clean-source package differs from native build')
        for name in sorted(set(report['artifact_sha256']) | set(generated) | {REPORT}):
            src = manifest.file_at(root, name)
            dst = destination / name; dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        shutil.copyfile(root / 'docs/smk37.md', destination / 'SMK37.md')
        shutil.copyfile(reproduction / REPORT, destination / 'reproduction-resource-report.json')
        files = {p.relative_to(destination).as_posix(): digest(p) for p in sorted(destination.rglob('*')) if p.is_file()}
        data = {'schema_version': 1, 'kind': KIND, 'version': version, 'model': model,
                'revision': metadata['firmware_revision'], 'source_distribution': source,
                'reproduction': {'method': 'clean verified source archive',
                    'package_sha256': digest(root / 'build' / package), 'source_sha256': source['sha256']}, 'files': files}
        (destination / MANIFEST).write_text(json.dumps(data, sort_keys=True, indent=2) + '\n')
        ci.write_checksums(destination)
        verify(destination, version, model, metadata['firmware_revision'])
    except Exception:
        shutil.rmtree(destination)
        raise


def stage(bundles, destination, version, revision):
    """Append all three checked models after FM-1 staging; never alter an existing asset."""
    bundles, destination = Path(bundles), Path(destination)
    ci.version(version)
    ci.verify_checksums(destination)
    fm1 = read(destination / 'BUILD-PROVENANCE.json')
    require(fm1.get('revision') == revision and fm1.get('version') == version, 'FM-1/SMK release identity mismatch')
    plans = []
    for model in fm1pkg_make.MODELS:
        root = manifest.file_at(bundles, model + '/' + MANIFEST).parent
        data = verify(root, version, model, revision)
        require(data['source_distribution'] == fm1['source_distribution'], 'FM-1/SMK source distribution mismatch')
        stem, package, product = names(version, model)
        paths = {'build/' + package: package, REPORT: stem + '-resource-report.json',
                 'build/gen/build-identity.json': stem + '-build-identity.json',
                 'build/gen/resolved-profile.json': stem + '-resolved-profile.json',
                 'build/profile-contract.json': stem + '-profile-contract.json',
                 'reproduction-resource-report.json': stem + '-reproduction-resource-report.json',
                 MANIFEST: stem + '-manifest.json'}
        plans.extend((manifest.file_at(root, src), destination / dst) for src, dst in paths.items())
    plans.append((manifest.file_at(bundles / 'pro', 'SMK37.md'), destination / 'SMK37.md'))
    require(len({dst.name for _, dst in plans}) == len(plans) and all(not dst.exists() for _, dst in plans),
            'SMK release assets collide with existing release assets')
    for src, dst in plans:
        shutil.copyfile(src, dst)
    ci.write_checksums(destination)
    ci.verify_checksums(destination)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command', choices=('prepare', 'stage'))
    ap.add_argument('--version', required=True)
    ap.add_argument('--model', choices=tuple(fm1pkg_make.MODELS))
    ap.add_argument('--root', type=Path, default=Path.cwd())
    ap.add_argument('--reproduction', type=Path)
    ap.add_argument('--bundles', type=Path, default=Path('downloaded-smk'))
    ap.add_argument('--destination', type=Path, required=True)
    ap.add_argument('--revision')
    a = ap.parse_args()
    try:
        if a.command == 'prepare':
            require(a.model is not None and a.reproduction is not None, 'prepare requires model and reproduction')
            prepare(a.root, a.version, a.model, a.reproduction, a.destination)
        else:
            require(a.revision is not None, 'stage requires revision')
            stage(a.bundles, a.destination, a.version, a.revision)
    except (ValueError, OSError, KeyError, fm1_install.InstallError) as error:
        raise SystemExit('smk-release: ' + str(error)) from error
    print('SMK experimental release assets verified')


if __name__ == '__main__':
    main()
