#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Single-Dev publication, stale writers, rollback and scoped cleanup contracts."""
import copy
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import dev_release as dev

SHA = 'a' * 40
OLD = 'b' * 40


def pull(sha=SHA, number=42, merged='2026-10-28T12:00:00Z'):
    return dict(number=number, merge_commit_sha=sha, merged_at=merged, updated_at=merged)


class GitHubFake:
    repo = 'owner/repo'

    def __init__(self, rolling=True):
        self.items = {1: dict(id=1, tag_name='v1.0', prerelease=False, draft=False),
                      2: dict(id=2, tag_name='dev-pr41-' + OLD[:12], prerelease=True, draft=False),
                      3: dict(id=3, tag_name='v1.1-rc1', prerelease=True, draft=False)}
        self.refs = {'v1.0': 'c' * 40, 'v1.1-rc1': 'd' * 40, self.items[2]['tag_name']: OLD}
        if rolling:
            self.items[4] = dict(id=4, tag_name=dev.TAG, prerelease=True, draft=False, body='old notes')
            self.refs[dev.TAG] = OLD
        self.checks = [pull(), pull()]
        self.calls = []
        self.fail_promotion = False
        self.next_id = 100

    def releases(self):
        return copy.deepcopy(list(self.items.values()))

    def request(self, method, path, data=None, missing=False):
        self.calls.append((method, path, copy.deepcopy(data)))
        if path.startswith('pulls?'):
            if not path.endswith('page=1'):
                return []
            return [self.checks.pop(0)]
        if path == 'releases' and method == 'POST':
            self.next_id += 1
            value = dict(data, id=self.next_id)
            self.items[value['id']] = value
            self.refs[data['tag_name']] = data['target_commitish']
            return copy.deepcopy(value)
        if path.startswith('releases/tags/'):
            return next((copy.deepcopy(x) for x in self.items.values()
                         if x['tag_name'] == path[len('releases/tags/'):]), None)
        if path.startswith('releases/'):
            identity = int(path.split('/')[1])
            if method == 'DELETE':
                self.items.pop(identity, None)
                return None
            if method == 'PATCH':
                if self.fail_promotion and identity > 100 and data.get('draft') is False:
                    raise RuntimeError('promotion failed')
                self.items[identity].update(data)
                if data.get('target_commitish'):
                    self.refs.setdefault(self.items[identity]['tag_name'], data['target_commitish'])
            return copy.deepcopy(self.items.get(identity))
        if path == 'git/matching-refs/tags/dev-':
            return [dict(ref='refs/tags/' + tag) for tag in self.refs if tag.startswith('dev-')]
        if path.startswith('git/ref/tags/'):
            sha = self.refs.get(path[len('git/ref/tags/'):])
            return dict(object=dict(type='commit', sha=sha)) if sha else None
        if path == 'git/refs':
            self.refs[data['ref'][len('refs/tags/'):]] = data['sha']
            return {}
        if path.startswith('git/refs/tags/'):
            tag = path[len('git/refs/tags/'):]
            if method == 'DELETE':
                self.refs.pop(tag, None)
            else:
                self.refs[tag] = data['sha']
            return {}
        raise AssertionError((method, path, data))


class DevReleaseTest(unittest.TestCase):
    def publish(self, api, upload_error=None):
        with patch.object(dev.subprocess, 'run', side_effect=upload_error) as upload:
            dev.publish(api, SHA, 42, '123', '1', 'short notes', [Path('verified.tar.gz')])
            return upload

    def assert_stable_preserved(self, api):
        self.assertEqual(api.items[1]['tag_name'], 'v1.0')
        self.assertEqual(api.items[3]['tag_name'], 'v1.1-rc1')
        self.assertEqual(api.refs['v1.0'], 'c' * 40)
        self.assertEqual(api.refs['v1.1-rc1'], 'd' * 40)

    def test_success_keeps_one_dev_and_prunes_only_managed_releases_and_tags(self):
        api = GitHubFake()
        api.items[5] = dict(id=5, tag_name='dev-staging-99-1', prerelease=True, draft=True)
        self.publish(api)
        self.assert_stable_preserved(api)
        self.assertEqual({x['tag_name'] for x in api.items.values()}, {'v1.0', 'v1.1-rc1', dev.TAG})
        rolling = next(x for x in api.items.values() if x['tag_name'] == dev.TAG)
        self.assertFalse(rolling['draft'])
        self.assertTrue(rolling['prerelease'])
        self.assertEqual(rolling['make_latest'], 'false')
        self.assertEqual(api.refs[dev.TAG], SHA)
        self.assertNotIn('dev-pr41-' + OLD[:12], api.refs)
        self.assertFalse(any(tag.startswith(('dev-staging-', 'dev-retired-')) for tag in api.refs))
        writes = [c for c in api.calls if c[0] == 'PATCH']
        self.assertEqual(writes[0][2]['draft'], True)  # old retained until candidate is ready

    def test_cleanup_removes_orphan_dev_tags_but_preserves_retained_release_tags(self):
        api = GitHubFake()
        api.refs['dev-staging-77-1'] = OLD
        api.items[6] = dict(id=6, tag_name='dev-pr7-' + OLD[:12], prerelease=False, draft=False)
        api.refs[api.items[6]['tag_name']] = OLD
        self.publish(api)
        self.assertNotIn('dev-staging-77-1', api.refs)
        self.assertEqual(api.refs[api.items[6]['tag_name']], OLD)

    def test_first_publication_migrates_legacy_dev_to_fixed_tag(self):
        api = GitHubFake(rolling=False)
        self.publish(api)
        self.assert_stable_preserved(api)
        self.assertEqual(api.refs[dev.TAG], SHA)
        self.assertEqual(sum(x['prerelease'] and not x['tag_name'].startswith('v')
                             for x in api.items.values()), 1)

    def test_stale_run_does_not_upload_or_mutate_any_release(self):
        api = GitHubFake()
        api.checks = [pull('c' * 40, 43)]
        before = copy.deepcopy((api.items, api.refs))
        upload = self.publish(api)
        upload.assert_not_called()
        self.assertEqual((api.items, api.refs), before)

    def test_merge_during_upload_discards_candidate_without_replacing_current(self):
        api = GitHubFake()
        api.checks = [pull(), pull('c' * 40, 43)]
        before = copy.deepcopy((api.items, api.refs))
        self.publish(api)
        self.assertEqual((api.items, api.refs), before)

    def test_upload_failure_keeps_previous_public_assets_and_removes_draft(self):
        api = GitHubFake()
        before = copy.deepcopy((api.items, api.refs))
        with self.assertRaises(subprocess.CalledProcessError):
            self.publish(api, subprocess.CalledProcessError(1, 'gh release upload'))
        self.assertEqual((api.items, api.refs), before)

    def test_promotion_failure_restores_previous_release_and_tag(self):
        api = GitHubFake()
        api.fail_promotion = True
        with self.assertRaisesRegex(RuntimeError, 'promotion failed'):
            self.publish(api)
        self.assert_stable_preserved(api)
        self.assertEqual(api.refs[dev.TAG], OLD)
        self.assertEqual(api.items[4]['tag_name'], dev.TAG)
        self.assertFalse(api.items[4]['draft'])
        self.assertEqual(api.items[4]['body'], 'old notes')
        self.assertFalse(any(x['tag_name'].startswith('dev-staging-') for x in api.items.values()))

    def test_first_promotion_failure_leaves_legacy_release_and_no_rolling_tag(self):
        api = GitHubFake(rolling=False)
        before = copy.deepcopy((api.items, api.refs))
        api.fail_promotion = True
        with self.assertRaises(RuntimeError):
            self.publish(api)
        self.assertEqual((api.items, api.refs), before)

    def test_same_second_merges_use_commit_order_instead_of_pr_number(self):
        api = GitHubFake()
        with patch.object(api, 'request', side_effect=[
                [pull(OLD, 99), pull(SHA, 42)], {'status': 'ahead'}, []]) as request:
            self.assertEqual(dev.latest_merge(api)['number'], 42)
            self.assertIn('compare/' + OLD + '...' + SHA, request.call_args_list[1].args[1])

    def test_latest_merge_uses_merge_time_and_pages_past_updated_old_prs(self):
        api = GitHubFake()
        older = pull(OLD, 99, '2026-10-01T00:00:00Z')
        older['updated_at'] = '2026-10-28T13:00:00Z'
        newest = pull()
        with patch.object(api, 'request', side_effect=[[older], [newest], []]) as request:
            self.assertEqual(dev.latest_merge(api)['number'], 42)
            self.assertEqual(request.call_count, 3)


if __name__ == '__main__':
    unittest.main()
