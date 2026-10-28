#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Release channel policy, provenance and complete commit notes (GitHub CLI)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()


def api(path):
    return json.loads(subprocess.check_output(['gh', 'api', path], text=True))


def dev_identity(pulls, repo, sha):
    matches = [p for p in pulls if p.get('merged_at') and
               p.get('merge_commit_sha') == sha and p['base']['ref'] == 'main' and
               p['base']['repo']['full_name'] == repo]
    if len(matches) != 1:
        return None
    number = matches[0]['number']
    # Match the compact commit identity used by the firmware's bounded ABOUT UI.
    # PR number and longer SHA stay in the release tag, title and provenance.
    return dict(pr=str(number), version=f'0.0-dev{sha[:8]}',
                tag=f'dev-pr{number}-{sha[:12]}')


def check_approval(version, sha, ref_type, ref_name, tested_commit, hardware_tested, evidence):
    if ref_type != 'tag' or ref_name != 'v' + version:
        raise ValueError('Publication must be dispatched on the matching vVERSION tag')
    if not re.fullmatch(r'[0-9a-f]{40}', tested_commit) or tested_commit != sha:
        raise ValueError('tested_commit must equal the full tagged commit SHA')
    if hardware_tested != 'true':
        raise ValueError('Explicit completion of the FM-1 release checklist is required')
    if not re.fullmatch(r'https://[^\s<>]+', evidence):
        raise ValueError('Provide an HTTPS link to the exact-package test report and known limitations')


def validate_package_digest(value):
    if not re.fullmatch(r'[0-9a-f]{64}', value):
        raise ValueError('Provide the 64 lowercase hex SHA-256 of the tested .fwsc')


def verify_tested_package(path, digest):
    validate_package_digest(digest)
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError('Rebuilt package differs from the hardware-tested .fwsc; do not publish')


def notes(channel, repo, sha, version, pr='', evidence='', base=None):
    root = f'https://github.com/{repo}'
    docs = f'{root}/blob/{sha}'
    if channel == 'dev':
        intro = ('**Experimental development firmware — not hardware-qualified.** '
                 'Regressions, audio glitches, failed boots/updates and loss of saved data are possible. '
                 'Use only if you can back up and recover your FM-1.\n\n'
                 f'Merged PR: {root}/pull/{pr}. This prerelease never replaces the stable Latest release.')
    else:
        intro = ('Maintainer-approved release: the author attests that the '
                 '[FM-1 release checklist](' + docs + '/docs/releases.md#device-release-checklist) '
                 'was completed for this exact versioned package. This is scoped test evidence, '
                 'not a guarantee for every device or setup.\n\n'
                 f'Test evidence, package SHA-256, tested setup and known limitations: {evidence}')
    history = git('log', '--reverse', '--format=- %h %s', f'{base}..{sha}' if base else sha)
    comparison = f'{root}/compare/{base}...{sha}' if base else f'{root}/commits/{sha}'
    return f'''# Felucca {version}

{intro}

## Exact build and validation

Commit: [{sha}]({root}/commit/{sha}). Profile: **standard**, release packaging, diagnostic flags off.
Automated target/host/browser, loader/package, resource and reproducibility gates passed:
{root}/actions/runs/{os.environ['GITHUB_RUN_ID']}
CI does not exercise physical USB/TRS, audio, power-loss recovery or your flash chip.

## Before installing / recovery

- Use an **M-VAVE FM-1**, stable power, a reliable USB data cable and a compatible installer.
- Back up projects, user presets/samples and settings before updating; keep a verified known-good package.
  Downgrades may not understand newer saved data. Do not assume that a backup or return to stock preserves everything.
- Download `felucca-{version}-release.tar.gz` and its `.sha256` sidecar; verify it before extraction.
  Install the **.fwsc**, never the raw .bin. The bundle includes provenance and licenses;
  complete pinned sources are also supplied separately.
- [Verification and installation prerequisites]({docs}/.github/CI.md#downloads-and-checksums)
  and [Python build/installer setup]({docs}/BUILDING.md).
- [Recovery guide]({docs}/docs/usb-rescue.md): ordinary MIDI installer while the app runs;
  hold **OCT− while powering on** for early MIDI-only USB rescue;
  if an interrupted loader says UPDATE STOPPED, keep USB/power connected and retry on the host.
  If those routes cannot run, use the documented **M-Flasher ROM recovery** route and its host prerequisites.
  Rescue requires a reachable compatible application/loader and supported flash; it is not a brick-proof guarantee.
- [Compatibility and experimental features]({docs}/docs/fork-features.md),
  [curated changes]({docs}/docs/changelog.md), and
  [release policy / remaining test limits]({docs}/docs/releases.md).

## Complete commit changelog

Range: {comparison}
All commits since the previous published stable ancestor, including changes without a PR.
Without a stable ancestor, this includes the complete reachable history.

{history}
'''


def previous_stable(repo, sha):
    # Paginate: an active Dev channel must not hide the previous stable release.
    releases = json.loads(subprocess.check_output(
        ['gh', 'api', '--paginate', '--slurp', f'repos/{repo}/releases?per_page=100'], text=True))
    candidates = []
    for page in releases:
        for release in page:
            tag = release['tag_name']
            if release['draft'] or release['prerelease'] or not tag.startswith('v'):
                continue
            commit = git('rev-parse', f'{tag}^{{commit}}')
            if subprocess.run(['git', 'merge-base', '--is-ancestor', commit, sha]).returncode == 0:
                candidates.append((release['published_at'], commit))
    return max(candidates)[1] if candidates else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['resolve-dev', 'approve', 'verify-tested-package', 'notes'])
    args = parser.parse_args()
    repo, sha = os.environ['GITHUB_REPOSITORY'], git('rev-parse', 'HEAD')
    if sha != os.environ['GITHUB_SHA']:
        raise ValueError('Checkout differs from the triggering revision')
    if args.command == 'resolve-dev':
        identity = dev_identity(api(f'repos/{repo}/commits/{sha}/pulls'), repo, sha)
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            for key, value in (identity or {}).items():
                output.write(f'{key}={value}\n')
        if not identity:
            print('No single merged main PR at this push tip; no Dev release.')
    elif args.command == 'verify-tested-package':
        verify_tested_package(Path('release-assets') / f"felucca-{os.environ['VERSION']}.fwsc",
                              os.environ['TESTED_PACKAGE_SHA256'])
    elif args.command == 'approve':
        validate_package_digest(os.environ.get('TESTED_PACKAGE_SHA256', ''))
        check_approval(os.environ['VERSION'], sha, os.environ['GITHUB_REF_TYPE'],
                       os.environ['GITHUB_REF_NAME'], os.environ.get('TESTED_COMMIT', ''),
                       os.environ.get('HARDWARE_TESTED', ''), os.environ.get('TEST_EVIDENCE', ''))
    else:
        Path('release-notes.md').write_text(notes(
            os.environ['CHANNEL'], repo, sha, os.environ['VERSION'], os.environ.get('PR_NUMBER', ''),
            os.environ.get('TEST_EVIDENCE', ''), previous_stable(repo, sha)))


if __name__ == '__main__':
    main()
