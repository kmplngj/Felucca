#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Replace the single latest-dev prerelease after validation; preserve tagged releases."""
import json
import os
from pathlib import Path
import re
import subprocess

TAG = 'latest-dev'
LEGACY = re.compile(r'dev-pr[1-9][0-9]*-[0-9a-f]{12}')
TEMPORARY = re.compile(r'dev-(?:staging-[0-9]+-[0-9]+|retired-[0-9]+)')


class GitHub:
    def __init__(self, repo):
        self.repo = repo
        self.root = f'repos/{repo}/'

    def request(self, method, path, data=None, missing=False):
        args = ['gh', 'api', '--method', method, self.root + path]
        if data is not None:
            args += ['--input', '-']
        result = subprocess.run(args, input=json.dumps(data) if data is not None else None,
                                text=True, capture_output=True)
        if result.returncode:
            if missing and '(HTTP 404)' in result.stderr:
                return None
            raise RuntimeError(result.stderr.strip())
        return json.loads(result.stdout) if result.stdout.strip() else None

    def releases(self):
        pages = json.loads(subprocess.check_output(
            ['gh', 'api', '--paginate', '--slurp', self.root + 'releases?per_page=100'], text=True))
        return [release for page in pages for release in page]


def latest_merge(api):
    latest = None
    page = 1
    while True:
        pulls = api.request('GET', f'pulls?state=closed&base=main&sort=updated&direction=desc&per_page=100&page={page}')
        if not pulls:
            return latest
        for pull in pulls:
            if not pull.get('merged_at'):
                continue
            if latest is None or pull['merged_at'] > latest['merged_at']:
                latest = pull
            elif (pull['merged_at'] == latest['merged_at'] and
                  pull['merge_commit_sha'] != latest['merge_commit_sha']):
                # REST merge timestamps have second resolution; use commit order
                # when two merges share a timestamp rather than guessing by PR id.
                comparison = api.request('GET', f"compare/{latest['merge_commit_sha']}...{pull['merge_commit_sha']}")
                if comparison['status'] == 'ahead':
                    latest = pull
        # updated_at >= merged_at, including PRs with later comments. Once the
        # remaining updated times precede the newest merge, no newer merge is hidden.
        if latest and pulls[-1]['updated_at'] < latest['merged_at']:
            return latest
        page += 1


def is_current(api, sha, pr):
    latest = latest_merge(api)
    return bool(latest and latest['merge_commit_sha'] == sha and str(latest['number']) == str(pr))


def cleanup(api, keep_id):
    for release in api.releases():
        tag = release['tag_name']
        managed = (LEGACY.fullmatch(tag) and release['prerelease'] or
                   TEMPORARY.fullmatch(tag) and release['draft'])
        if release['id'] != keep_id and managed:
            api.request('DELETE', f"releases/{release['id']}")
            api.request('DELETE', f'git/refs/tags/{tag}', missing=True)
    # Also remove a tag left behind if an earlier cleanup lost its connection
    # between deleting the release and deleting its ref. Keep every retained
    # release's tag, including an explicitly non-prerelease dev-named version.
    retained = {release['tag_name'] for release in api.releases()}
    for ref in api.request('GET', 'git/matching-refs/tags/dev-'):
        tag = ref['ref'][len('refs/tags/'):]
        if tag not in retained and (LEGACY.fullmatch(tag) or TEMPORARY.fullmatch(tag)):
            api.request('DELETE', f'git/refs/tags/{tag}', missing=True)


def publish(api, sha, pr, run_id, attempt, body, assets):
    if not is_current(api, sha, pr):
        print('A newer PR has merged; this build will not replace Latest Dev.')
        return
    # The workflow serializes this entire operation without cancelling its writer.
    # Upload a hidden candidate first; a failed upload leaves the public build intact.
    staging = f'dev-staging-{run_id}-{attempt}'
    title = f'Latest Dev — PR #{pr} @ {sha[:12]}'
    candidate = api.request('POST', 'releases', dict(tag_name=staging, target_commitish=sha,
                            name=title, body=body, draft=True, prerelease=True, make_latest='false'))
    promoted = False
    retired = None
    old_ref = None
    ref_changed = False
    try:
        subprocess.run(['gh', 'release', 'upload', staging, '--repo', api.repo,
                        *[str(path) for path in assets]], check=True)
        if not is_current(api, sha, pr):
            print('A newer PR merged during upload; discarding this candidate.')
            return
        old = api.request('GET', f'releases/tags/{TAG}', missing=True)
        old_ref = api.request('GET', f'git/ref/tags/{TAG}', missing=True)
        if old and (not old['prerelease'] or not old_ref or old_ref['object']['type'] != 'commit'):
            raise ValueError('latest-dev must be a prerelease with a lightweight commit tag')
        if old:
            retired = old
            api.request('PATCH', f"releases/{old['id']}",
                        dict(tag_name=f"dev-retired-{old['id']}", draft=True,
                             target_commitish=old_ref['object']['sha']))
        # Set before the request: a timed-out mutation may already have applied.
        ref_changed = True
        if old_ref:
            api.request('PATCH', f'git/refs/tags/{TAG}', dict(sha=sha, force=True))
        else:
            api.request('POST', 'git/refs', dict(ref=f'refs/tags/{TAG}', sha=sha))
        api.request('PATCH', f"releases/{candidate['id']}",
                    dict(tag_name=TAG, target_commitish=sha, draft=False,
                         prerelease=True, make_latest='false'))
        promoted = True
    except Exception:
        # A timed-out response may still have promoted the candidate server-side.
        current = api.request('GET', f"releases/{candidate['id']}", missing=True)
        if current and current['tag_name'] == TAG and not current['draft']:
            promoted = True
        else:
            if ref_changed:
                if old_ref:
                    api.request('PATCH', f'git/refs/tags/{TAG}', dict(sha=old_ref['object']['sha'], force=True))
                else:
                    api.request('DELETE', f'git/refs/tags/{TAG}', missing=True)
            if retired:
                api.request('PATCH', f"releases/{retired['id']}",
                            dict(tag_name=TAG, draft=False, prerelease=True, make_latest='false'))
                api.request('DELETE', f"git/refs/tags/dev-retired-{retired['id']}", missing=True)
            raise
    finally:
        if not promoted:
            api.request('DELETE', f"releases/{candidate['id']}", missing=True)
            api.request('DELETE', f'git/refs/tags/{staging}', missing=True)
    cleanup(api, candidate['id'])
    print(f'Published {TAG}: PR #{pr} at {sha}')


def main():
    api = GitHub(os.environ['GITHUB_REPOSITORY'])
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    if sha != os.environ['GITHUB_SHA']:
        raise ValueError('Checkout differs from triggering revision')
    publish(api, sha, os.environ['PR_NUMBER'], os.environ['GITHUB_RUN_ID'],
            os.environ['GITHUB_RUN_ATTEMPT'], Path('release-notes.md').read_text(),
            sorted(Path('release-assets').iterdir()))


if __name__ == '__main__':
    main()
