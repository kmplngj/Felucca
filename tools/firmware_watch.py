#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Deterministic firmware intake. Git caches are data, never executable checkouts.

The JSONL journal is authoritative; state.json is a recoverable checkpoint cache.
All CLI operations take a short writer lock. Schedulers must additionally hold a
run-level lease throughout sync, human review, record and checkpoint. Supply an
absolute --lease-dir shared by every worktree; its default cache location only
coordinates callers sharing that cache.
"""
import argparse
import contextlib
import copy
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile

SCHEMA_VERSION = 1
TERMINAL = frozenset(('bug', 'optimization', 'feature', 'backport',
                      'already_present', 'existing_issue', 'not_applicable'))
NONTERMINAL = frozenset(('pending', 'needs_input'))
RUNTIME_FIELDS = frozenset(('recent_frontiers', 'pinned_recent_targets',
                            'historical_reviewed', 'recent_reviewed',
                            'last_reviewed_sha'))
MARKER = '<!-- felucca-firmware-watch-journal:v1 -->'
SHA_RE = re.compile(r'[0-9a-f]{40}\Z')
REPO_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*\Z')
FENCES = re.compile(r'^```json[ \t]*\r?\n(.*?)^```[ \t]*$', re.M | re.S)


class WatchError(ValueError):
    """Invalid ledger data or a source which cannot be safely enumerated."""


def require(condition, message):
    if not condition:
        raise WatchError(message)


def repository_name(value):
    require(isinstance(value, str) and REPO_RE.fullmatch(value),
            'repository must be OWNER/NAME')
    require(all(part not in ('.', '..') for part in value.split('/')),
            'unsafe repository path')
    return value


def sha(value):
    require(isinstance(value, str) and SHA_RE.fullmatch(value),
            'expected a full lowercase 40-character source SHA')
    return value


def branch_name(value):
    require(isinstance(value, str) and value and not value.startswith(('-', '/'))
            and not value.endswith(('/', '.', '.lock'))
            and not any(x in value for x in ('..', '@{', '//'))
            and not re.search(r'[\x00-\x20\x7f~^:?*\[\\]', value)
            and all(not p.startswith('.') and not p.endswith('.lock')
                    for p in value.split('/')), 'invalid tracked branch')
    return value


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + '\n').encode()


def read_json(path):
    with Path(path).open(encoding='utf-8') as stream:
        return json.load(stream)


def fsync_dir(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fsync_dir(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_json(path, value):
    atomic_bytes(path, json_bytes(value))


@contextlib.contextmanager
def writer_lock(data_dir):
    """Portable fail-closed lease; abandoned locks require explicit operator removal."""
    directory = Path(data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / '.writer-lock'
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise WatchError('another writer holds ' + str(lock)) from error
    try:
        (lock / 'owner').write_text(str(os.getpid()) + '\n', encoding='ascii')
        yield
    finally:
        (lock / 'owner').unlink(missing_ok=True)
        lock.rmdir()


def run(arguments):
    environment = dict(os.environ, GIT_TERMINAL_PROMPT='0', GIT_NO_REPLACE_OBJECTS='1')
    # Do not let the caller's repository/config overlays alter a source DAG.
    for key in list(environment):
        if key.startswith(('GIT_CONFIG_', 'GIT_OBJECT_', 'GIT_ALTERNATE_')) or key in (
                'GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR', 'GIT_INDEX_FILE',
                'GIT_SHALLOW_FILE', 'GIT_NAMESPACE'):
            environment.pop(key, None)
    result = subprocess.run([str(a) for a in arguments], capture_output=True,
                            text=True, encoding='utf-8', errors='strict',
                            env=environment, timeout=180)
    if result.returncode:
        raise WatchError('command failed: ' + ' '.join(map(str, arguments[:5]))
                         + ': ' + result.stderr.strip())
    return result.stdout


def parse_fenced(body, label):
    blocks = FENCES.findall(body)
    require(len(blocks) == 1, label + ': expected exactly one fenced JSON object')
    value = json.loads(blocks[0])
    require(isinstance(value, dict), label + ': JSON must be an object')
    return value


def review_key(record):
    return (repository_name(record['repository']), sha(record['source_sha']))


def review_content(record):
    return {k: v for k, v in record.items() if k != 'provenance'}


def validate_review_structure(record, destination_repo=None):
    require(isinstance(record, dict), 'record must be an object')
    review_key(record)
    require(record.get('disposition') in TERMINAL | NONTERMINAL, 'unknown disposition')
    sha(record.get('felucca_comparison_sha'))
    require(record.get('queue') in ('recent', 'history'), 'invalid queue')
    required_text = ['commit_title', 'rationale']
    if 'provenance' not in record or 'run_id' in record:
        required_text.append('run_id')
    for field in required_text:
        require(isinstance(record.get(field), str) and record[field].strip(), field + ' is required')
    for field in ('parents', 'branches', 'changed_paths', 'source_evidence', 'native_evidence', 'issue_urls'):
        require(isinstance(record.get(field), list) and all(isinstance(v, str) for v in record[field]),
                field + ' must be an array of strings')
        require(len(record[field]) == len(set(record[field])), field + ' contains duplicates')
    require(record['branches'], 'branch membership is required')
    for parent in record['parents']:
        sha(parent)
    for branch in record['branches']:
        branch_name(branch)
    for path in record['changed_paths']:
        require(path and not path.startswith('/') and '..' not in PurePosixPath(path).parts
                and '\x00' not in path, 'unsafe changed path')
    for field in ('source_evidence', 'native_evidence'):
        require(record[field] and all(re.fullmatch(r'https://[^\s/]+/\S+', v) for v in record[field]),
                field + ' requires HTTPS evidence URLs')
    source_prefix = 'https://github.com/' + record['repository']
    require(any(u == source_prefix + '/commit/' + record['source_sha']
                or u.startswith(source_prefix + '/commit/' + record['source_sha'] + '#')
                or u.startswith(source_prefix + '/blob/' + record['source_sha'] + '/')
                for u in record['source_evidence']),
            'source_evidence must identify the exact repository and full source SHA')
    issue_prefix = re.escape(destination_repo) if destination_repo else r'[^/]+/[^/]+'
    require(all(re.fullmatch(r'https://github\.com/' + issue_prefix
                            + r'/(?:issues|pull)/[1-9][0-9]*(?:#\S+)?', u) for u in record['issue_urls']),
            'issue_urls must link destination issues')
    if record['disposition'] in {'bug', 'optimization', 'feature', 'backport', 'existing_issue'}:
        require(record['issue_urls'], 'actionable disposition requires linked issue_urls')
    if 'provenance' in record:
        provenance = record['provenance']
        require(isinstance(provenance, dict) and type(provenance.get('comment_id')) is int
                and type(provenance.get('record_index')) is int and provenance['record_index'] >= 0
                and isinstance(provenance.get('comment_url'), str)
                and re.fullmatch(r'https://github\.com/[^/]+/[^/]+/issues/[1-9][0-9]*#issuecomment-[0-9]+',
                                 provenance['comment_url']), 'malformed imported provenance')


def effective_reviews(records):
    """Reconcile nonterminal attempts; never transfer coverage between exact keys."""
    effective = {}
    for record in records:
        validate_review_structure(record)
        key = review_key(record)
        require(record.get('disposition') in TERMINAL | NONTERMINAL,
                'unknown disposition for ' + '/'.join(key))
        previous = effective.get(key)
        if previous and previous['disposition'] in TERMINAL:
            if record['disposition'] in TERMINAL:
                require(review_content(previous) == review_content(record),
                        'conflicting terminal records for ' + '/'.join(key))
            continue
        effective[key] = record
    return effective


class Watch:
    def __init__(self, data_dir='data/firmware-watch', cache_dir='build/firmware-watch', lease_dir=None):
        self.data_dir = Path(data_dir)
        self.cache_dir = Path(cache_dir)
        self.lease_dir = Path(lease_dir) if lease_dir is not None else self.cache_dir
        require(lease_dir is None or self.lease_dir.is_absolute(),
                'lease-dir must be an absolute shared directory across worktrees')

    def cache(self, repository):
        return self.cache_dir / 'repos' / (repository_name(repository) + '.git')

    def git(self, repository, *arguments):
        return run(['git', '--git-dir=' + str(self.cache(repository)),
                    '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
                    '-c', 'gc.auto=0', *arguments])

    def load(self):
        sources = read_json(self.data_dir / 'sources.json')
        state = read_json(self.data_dir / 'state.json')
        require(sources.get('schema_version') == SCHEMA_VERSION
                and state.get('schema_version') == SCHEMA_VERSION, 'unsupported schema version')
        repository_name(sources['destination_repo'])
        configured = sources['repositories']
        pending = sources.get('pending_source_additions', [])
        require(isinstance(configured, list) and isinstance(pending, list),
                'repositories and pending_source_additions must be arrays')
        names = []
        for source in configured + pending:
            names.append(repository_name(source['repository']))
            require(type(source.get('repository_id')) is int and source['repository_id'] > 0,
                    'source requires a stable positive repository_id')
            require(isinstance(source.get('historical_targets'), dict)
                    and source['historical_targets'], 'source requires historical_targets')
            for branch, target in source['historical_targets'].items():
                branch_name(branch)
                sha(target)
            if 'branches' in source:
                require(set(source['branches']) == set(source['historical_targets']),
                        'branches must exactly match historical_targets')
        require(len(names) == len(set(n.lower() for n in names)), 'duplicate source repository')
        states = state['repositories']
        require(isinstance(states, list), 'state.repositories must be an array')
        require(len(states) == len(configured)
                and {s['repository'] for s in states} == {s['repository'] for s in configured},
                'state and source repository sets differ')
        for source in configured:
            runtime = self.runtime(state, source['repository'])
            for field in ('recent_frontiers', 'pinned_recent_targets'):
                require(set(runtime[field]) == set(source['historical_targets']),
                        'state branches differ from tracked branches')
                for target in runtime[field].values():
                    sha(target)
        records = self.records()
        for record in records:
            validate_review_structure(record, sources['destination_repo'])
            require(record['repository'] in {s['repository'] for s in configured},
                    'journal record names an unconfigured repository')
        effective_reviews(records)
        self.validate_migration(records, sources)
        if 'round_robin_processed_records' in state:
            processed = state['round_robin_processed_records']
            require(type(processed) is int
                    and sum('provenance' in r for r in records) <= processed <= len(records),
                    'invalid round-robin journal cursor')
            require(state.get('round_robin_journal_prefix_sha256')
                    == hashlib.sha256(json_bytes(records[:processed])).hexdigest(),
                    'round-robin journal prefix changed; manual recovery required')
        return sources, state, records

    def validate_migration(self, records, sources):
        manifest = self.data_dir / 'migration-report.json'
        if not manifest.exists():
            return
        report = read_json(manifest)
        raw = (self.data_dir / 'legacy-issue-152.json').read_bytes()
        require(report.get('snapshot_sha256') == hashlib.sha256(raw).hexdigest(),
                'migration snapshot digest differs from preserved archive')
        snapshot = json.loads(raw)
        originals = []
        comments = 0
        for comment in snapshot['comments']:
            if MARKER not in comment['body']:
                continue
            comments += 1
            document = parse_fenced(comment['body'], 'archived journal comment')
            require(document.get('schema_version') == 1 and isinstance(document.get('records'), list),
                    'malformed archived journal')
            for index, original in enumerate(document['records']):
                require(isinstance(original.get('run_id', document.get('run_id')), str)
                        and original.get('run_id', document.get('run_id')).strip(),
                        'imported assessment requires record or journal envelope run_id')
                record = copy.deepcopy(original)
                record['provenance'] = {'comment_id': comment['id'], 'comment_url': comment['url'],
                                        'record_index': index}
                originals.append(record)
        effective = effective_reviews(originals)
        config = parse_fenced(snapshot['body'], 'archived issue body')
        require(sources['destination_repo'] == config['destination_repo'],
                'destination repository differs from immutable migration archive')
        current_sources = {source['repository']: source
                           for source in sources['repositories'] + sources.get('pending_source_additions', [])}
        for original in config['repositories'] + config.get('pending_source_additions', []):
            current = current_sources.get(original['repository'])
            require(current is not None and current['repository_id'] == original['repository_id'],
                    'original registered source identity changed: ' + original['repository'])
            require(all(current['historical_targets'].get(branch) == target
                        for branch, target in original['historical_targets'].items()),
                    'immutable original historical target changed: ' + original['repository'])
        expected = {'schema_version': 1, 'license': 'GPL-3.0-only',
                    'issue_url': snapshot['issue_url'], 'comments': len(snapshot['comments']),
                    'journal_comments': comments, 'journal_records': len(originals),
                    'unique_pairs': len(effective),
                    'terminal_pairs': sum(r['disposition'] in TERMINAL for r in effective.values()),
                    'nonterminal_pairs': sum(r['disposition'] in NONTERMINAL for r in effective.values()),
                    'configured_repositories': len(config['repositories']),
                    'pending_sources': len(config.get('pending_source_additions', [])),
                    'configured_branches': sum(len(r['historical_targets']) for r in config['repositories'])}
        require(all(report.get(k) == v for k, v in expected.items()),
                'migration report counts or metadata differ from preserved archive')
        imported = [r for r in records if 'provenance' in r]
        require(imported == originals, 'imported journal records differ from preserved archive')

    @staticmethod
    def runtime(state, repository):
        return next(s for s in state['repositories'] if s['repository'] == repository)

    def records(self):
        path = self.data_dir / 'reviews.jsonl'
        records = []
        with path.open('rb') as stream:
            for number, line in enumerate(stream, 1):
                require(line.endswith(b'\n'), 'incomplete journal tail; run record/checkpoint to recover')
                record = json.loads(line)
                require(isinstance(record, dict), 'journal line must be an object')
                records.append(record)
        return records

    def recover_tail(self):
        """Fail closed on a torn append; recovery requires verified Git provenance."""
        path = self.data_dir / 'reviews.jsonl'
        if path.exists():
            contents = path.read_bytes()
            require(not contents or contents.endswith(b'\n'),
                    'incomplete journal tail; preserve bytes and recover from verified Git manually')

    def migrate(self, snapshot_path):
        raw = Path(snapshot_path).read_bytes()
        snapshot = json.loads(raw)
        config = parse_fenced(snapshot['body'], 'issue body')
        require(config.get('schema_version') == 1, 'unsupported legacy schema')
        records = []
        journal_comments = 0
        for comment in snapshot['comments']:
            if MARKER not in comment['body']:
                continue
            journal_comments += 1
            document = parse_fenced(comment['body'], 'journal comment ' + str(comment['id']))
            require(document.get('schema_version') == 1 and isinstance(document.get('records'), list),
                    'malformed journal comment')
            for index, original in enumerate(document['records']):
                require(isinstance(original, dict), 'journal record must be an object')
                require(isinstance(original.get('run_id', document.get('run_id')), str)
                        and original.get('run_id', document.get('run_id')).strip(),
                        'imported assessment requires record or journal envelope run_id')
                record = copy.deepcopy(original)
                require('provenance' not in record, 'legacy provenance field collision')
                record['provenance'] = {'comment_id': comment['id'],
                                        'comment_url': comment['url'], 'record_index': index}
                records.append(record)
        effective = effective_reviews(records)
        sources = {'schema_version': 1, 'destination_repo': config['destination_repo'],
                   'repositories': [],
                   'pending_source_additions': copy.deepcopy(config.get('pending_source_additions', []))}
        state = {k: copy.deepcopy(v) for k, v in config.items()
                 if k not in ('repositories', 'pending_source_additions', 'destination_repo')}
        state['repositories'] = []
        for original in config['repositories']:
            sources['repositories'].append({k: copy.deepcopy(v) for k, v in original.items()
                                            if k not in RUNTIME_FIELDS})
            state['repositories'].append({k: copy.deepcopy(v) for k, v in original.items()
                                          if k in RUNTIME_FIELDS or k == 'repository'})
        report = {'schema_version': 1, 'license': 'GPL-3.0-only',
                  'issue_url': snapshot['issue_url'],
                  'snapshot_sha256': hashlib.sha256(raw).hexdigest(),
                  'comments': len(snapshot['comments']), 'journal_comments': journal_comments,
                  'journal_records': len(records), 'unique_pairs': len(effective),
                  'terminal_pairs': sum(r['disposition'] in TERMINAL for r in effective.values()),
                  'nonterminal_pairs': sum(r['disposition'] in NONTERMINAL for r in effective.values()),
                  'configured_repositories': len(sources['repositories']),
                  'pending_sources': len(sources['pending_source_additions']),
                  'configured_branches': sum(len(r['historical_targets']) for r in sources['repositories'])}
        existing = self.data_dir / 'migration-report.json'
        if existing.exists():
            require(read_json(existing) == report, 'migration already exists for a different snapshot')
            self.load()
            return report
        artifacts = {'legacy-issue-152.json': raw,
                     'sources.json': json_bytes(sources), 'state.json': json_bytes(state),
                     'reviews.jsonl': b''.join((json.dumps(r, sort_keys=True, ensure_ascii=False)
                                               + '\n').encode() for r in records)}
        # Validate the complete import before publishing any files. On interruption,
        # rerunning the same migration fills missing files without overwriting edits.
        with tempfile.TemporaryDirectory(prefix='firmware-watch-import-') as temporary:
            for name, contents in artifacts.items():
                (Path(temporary) / name).write_bytes(contents)
            Watch(temporary, self.cache_dir).load()
        for name, contents in artifacts.items():
            path = self.data_dir / name
            require(not path.exists() or path.read_bytes() == contents,
                    'refusing to overwrite existing ledger: ' + name)
        for name, contents in artifacts.items():
            atomic_bytes(self.data_dir / name, contents)
        atomic_json(existing, report)
        return report

    def lease(self, action, owner):
        require(isinstance(owner, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', owner),
                'lease owner must be a safe nonempty run ID (at most 128 characters)')
        self.lease_dir.mkdir(parents=True, exist_ok=True)
        lease = self.lease_dir / '.run-lease'
        if action == 'acquire':
            try:
                lease.mkdir()
            except FileExistsError as error:
                raise WatchError('another run holds ' + str(lease)
                                 + '; never auto-remove an abandoned lease') from error
            atomic_bytes(lease / 'owner', (owner + '\n').encode())
            fsync_dir(self.lease_dir)
        else:
            require(lease.is_dir() and (lease / 'owner').read_text().strip() == owner,
                    'run lease is absent or belongs to another owner')
            (lease / 'owner').unlink()
            lease.rmdir()
            fsync_dir(self.lease_dir)
        return {'lease': action, 'owner': owner}

    def validate(self):
        sources, state, records = self.load()
        return {'valid': True, 'repositories': len(sources['repositories']),
                'pending_sources': len(sources.get('pending_source_additions', [])),
                'journal_records': len(records),
                'terminal_pairs': sum(r['disposition'] in TERMINAL
                                      for r in effective_reviews(records).values())}

    def rev_list(self, repository, targets, exclude=()):
        targets = sorted(set(sha(x) for x in targets))
        exclude = sorted(set(sha(x) for x in exclude))
        if not targets:
            return []
        return self.git(repository, 'rev-list', '--topo-order', '--reverse',
                        *targets, *('^' + x for x in exclude), '--').splitlines()

    def check_cache(self, source, runtime):
        repository = source['repository']
        require(self.cache(repository).is_dir(), 'missing complete git cache; run sync')
        require(self.git(repository, 'rev-parse', '--is-bare-repository').strip() == 'true',
                'cache must be a bare repository')
        require(self.git(repository, 'rev-parse', '--is-shallow-repository').strip() == 'false',
                'shallow source history is blocked')
        require(not (self.cache(repository) / 'info' / 'grafts').exists(), 'grafted history is blocked')
        for group in (source['historical_targets'], runtime['recent_frontiers'],
                      runtime['pinned_recent_targets']):
            for target in group.values():
                require(self.git(repository, 'cat-file', '-t', sha(target)).strip() == 'commit',
                        'target is not a commit')
        # Traversal forces missing parent objects to fail; counts never come from caches.
        self.rev_list(repository, list(source['historical_targets'].values())
                      + list(runtime['pinned_recent_targets'].values())
                      + list(runtime['recent_frontiers'].values()))
        # Frontiers are a cache, never proof of completed review. Every newer
        # commit hidden by their union must have an exact terminal journal entry.
        hidden = self.rev_list(repository, runtime['recent_frontiers'].values(),
                               source['historical_targets'].values())
        completed = {key for key, record in effective_reviews(self.records()).items()
                     if record['disposition'] in TERMINAL}
        gaps = [commit for commit in hidden if (repository, commit) not in completed]
        require(not gaps, 'frontier skips unreviewed recent commits: '
                + ', '.join(gaps[:5]) + (' (and more)' if len(gaps) > 5 else ''))

    def inventories(self, source, runtime):
        self.check_cache(source, runtime)
        repository = source['repository']
        history = self.rev_list(repository, source['historical_targets'].values())
        recent = self.rev_list(repository, runtime['pinned_recent_targets'].values(),
                               runtime['recent_frontiers'].values())
        # A preserved history target may intentionally be outside the reconciled tip.
        historical = set(history)
        return {'history': history, 'recent': [s for s in recent if s not in historical]}

    def summary(self):
        sources, state, records = self.load()
        completed = {k for k, v in effective_reviews(records).items() if v['disposition'] in TERMINAL}
        rows, blockers = [], []
        for source in sources['repositories']:
            repository = source['repository']
            runtime = self.runtime(state, repository)
            try:
                require(not runtime.get('blocker'), runtime.get('blocker'))
                inventories = self.inventories(source, runtime)
                row = {'repository': repository}
                for queue, commits in inventories.items():
                    reviewed = sum((repository, s) in completed for s in commits)
                    row[queue] = {'total': len(commits), 'reviewed': reviewed,
                                  'remaining': len(commits) - reviewed}
                row['terminal_pairs'] = sum(k[0] == repository for k in completed)
                rows.append(row)
            except (WatchError, OSError, subprocess.SubprocessError) as error:
                blockers.append({'repository': repository, 'reason': str(error)})
        blockers.extend({'repository': name, 'reason': reason}
                        for name, reason in sorted(state.get('pending_source_blockers', {}).items()))
        complete = not blockers and not sources.get('pending_source_additions')
        known_history = sum(r['history']['remaining'] for r in rows)
        known_recent = sum(r['recent']['remaining'] for r in rows)
        return {'schema_version': 1, 'repositories': rows, 'blockers': blockers,
                'terminal_pairs': len(completed), 'pending_sources': sources.get('pending_source_additions', []),
                'remaining_history': known_history if complete else None,
                'remaining_recent': known_recent if complete else None,
                'known_remaining_history': known_history, 'known_remaining_recent': known_recent,
                'complete_inventory': complete}

    def metadata(self, source, runtime, commit, queue):
        repository = source['repository']
        parents = self.git(repository, 'show', '-s', '--format=%P', commit, '--').strip().split()
        title = self.git(repository, 'show', '-s', '--format=%s', commit, '--').rstrip('\n')
        paths = self.git(repository, 'diff-tree', '--root', '-m', '--no-commit-id',
                         '--name-only', '-r', '-z', commit, '--').split('\0')
        branches = []
        for branch in sorted(source['historical_targets']):
            targets = [source['historical_targets'][branch], runtime['pinned_recent_targets'][branch]]
            if commit in self.rev_list(repository, targets):
                branches.append(branch)
        return {'repository': repository, 'source_sha': commit, 'parents': parents,
                'branches': branches, 'queue': queue, 'commit_title': title,
                'changed_paths': sorted(set(p for p in paths if p)),
                'source_evidence': ['https://github.com/' + repository + '/commit/' + commit]}

    def queue(self, limit):
        require(type(limit) is int and limit > 0, 'queue limit must be positive')
        sources, state, records = self.load()
        effective = effective_reviews(records)
        completed = {k for k, v in effective.items() if v['disposition'] in TERMINAL}
        pools, blockers = {'recent': [], 'history': []}, []
        order = sources['repositories']
        start = state.get('round_robin_next_repository_index', 0)
        require(type(start) is int and start >= 0, 'invalid round-robin cursor')
        if order:
            start %= len(order)
            order = order[start:] + order[:start]
        for source in order:
            repository = source['repository']
            runtime = self.runtime(state, repository)
            try:
                require(not runtime.get('blocker'), runtime.get('blocker'))
                inventories = self.inventories(source, runtime)
                for queue in pools:
                    commits = [s for s in inventories[queue] if (repository, s) not in completed]
                    if commits:
                        pools[queue].append([source, runtime, commits])
            except (WatchError, OSError, subprocess.SubprocessError) as error:
                blockers.append({'repository': repository, 'reason': str(error)})
        # Weighted reservations, then spill unused seats to the other queue.
        budgets = {'recent': math.ceil(limit * .6), 'history': limit - math.ceil(limit * .6)}
        if limit > 1 and pools['recent'] and pools['history']:
            budgets['history'] = max(1, budgets['history'])
            budgets['recent'] = limit - budgets['history']
        tasks, selected = [], set()

        def take(queue):
            while pools[queue]:
                source, runtime, commits = pools[queue].pop(0)
                commit = commits.pop(0)
                if commits:
                    pools[queue].append([source, runtime, commits])
                key = (source['repository'], commit)
                if key in selected:
                    continue
                selected.add(key)
                task = self.metadata(source, runtime, commit, queue)
                previous = effective.get(key)
                if previous:
                    task['previous_assessment'] = previous
                if state.get('latest_felucca_comparison_sha'):
                    task['suggested_felucca_comparison_sha'] = state['latest_felucca_comparison_sha']
                tasks.append(task)
                return True
            return False

        for queue in ('recent', 'history'):
            for _ in range(budgets[queue]):
                if not take(queue):
                    break
        while len(tasks) < limit:
            if not (take('recent') or take('history')):
                break
        return {'tasks': tasks, 'blockers': blockers,
                'notice': 'Tasks require evidence-based assessment; queueing grants no review coverage.'}

    def sync_source(self, source, runtime):
        repository = repository_name(source['repository'])
        identity = json.loads(run(['gh', 'api', 'repos/' + repository]))
        require(identity.get('id') == source['repository_id'], 'repository stable ID changed')
        require(identity.get('full_name', '').lower() == repository.lower(), 'repository was renamed or redirected')
        cache = self.cache(repository)
        if not cache.exists():
            cache.parent.mkdir(parents=True, exist_ok=True)
            run(['git', 'init', '--bare', str(cache)])
        require(self.git(repository, 'rev-parse', '--is-bare-repository').strip() == 'true',
                'cache must be a bare repository')
        require(self.git(repository, 'rev-parse', '--is-shallow-repository').strip() == 'false',
                'shallow source history is blocked')
        require(not (cache / 'info' / 'grafts').exists(), 'grafted history is blocked')
        # Fetch explicit source branches only; disable auto-following tags/submodules.
        refspecs = ['+refs/heads/' + branch_name(b) + ':refs/watch/' + b
                    for b in sorted(source['historical_targets'])]
        self.git(repository, '-c', 'protocol.file.allow=never', 'fetch', '--no-tags',
                 '--no-recurse-submodules', 'https://github.com/' + repository + '.git', *refspecs)
        targets = set(source['historical_targets'].values()) | set(runtime['recent_frontiers'].values()) \
            | set(runtime['pinned_recent_targets'].values())
        for target in sorted(targets):
            sha(target)
            try:
                self.git(repository, 'cat-file', '-e', target + '^{commit}')
            except WatchError:
                self.git(repository, '-c', 'protocol.file.allow=never', 'fetch', '--no-tags',
                         '--no-recurse-submodules', 'https://github.com/' + repository + '.git', target)
            # Retain old-only objects even if no current public branch contains them.
            self.git(repository, 'update-ref', 'refs/watch-preserved/' + target, target)
        self.check_cache(source, runtime)
        observed = {}
        for branch in sorted(source['historical_targets']):
            tip = self.git(repository, 'rev-parse', '--verify', 'refs/watch/' + branch + '^{commit}').strip()
            sha(tip)
            frozen = runtime['pinned_recent_targets'][branch]
            require(frozen in self.rev_list(repository, [tip]),
                    'branch rewrite: live tip does not contain frozen target for ' + branch)
            previous = runtime.get('observed_tips', {}).get(branch)
            if previous:
                require(previous in self.rev_list(repository, [tip]),
                        'branch rewrite since previous sync for ' + branch)
            observed[branch] = tip
        # Verify full live DAG as well as frozen targets, before recording successful sync.
        self.rev_list(repository, observed.values())
        runtime['observed_tips'] = observed
        runtime.pop('blocker', None)
        runtime['identity_verified'] = True

    def sync(self, repository=None):
        self.recover_tail()
        self.recover_transaction()
        sources, state, _ = self.load()
        if repository:
            repository_name(repository)
            require(repository in {s['repository'] for s in sources['repositories']
                                    + sources.get('pending_source_additions', [])}, 'unknown source')
        synced, blockers = [], []
        # A pending source is admitted only after all verification succeeds; existing
        # intervals are left unchanged. Atomic sources/state pair recovery is explicit.
        for source in sources['repositories']:
            name = source['repository']
            if repository and repository != name:
                continue
            runtime = self.runtime(state, name)
            try:
                self.sync_source(source, runtime)
                synced.append(name)
            except (WatchError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
                runtime['blocker'] = str(error)
                blockers.append({'repository': name, 'reason': str(error)})
        remaining = []
        for pending in sources.get('pending_source_additions', []):
            name = pending['repository']
            if repository and repository != name:
                remaining.append(pending)
                continue
            source = {k: copy.deepcopy(v) for k, v in pending.items() if k not in RUNTIME_FIELDS}
            runtime = {k: copy.deepcopy(v) for k, v in pending.items()
                       if k in RUNTIME_FIELDS or k == 'repository'}
            runtime.setdefault('recent_frontiers', copy.deepcopy(source['historical_targets']))
            runtime.setdefault('pinned_recent_targets', copy.deepcopy(source['historical_targets']))
            try:
                self.sync_source(source, runtime)
                # This source has no active interval yet: freeze its first live
                # inventory now, keeping the registered historical pin immutable.
                runtime['pinned_recent_targets'] = copy.deepcopy(runtime['observed_tips'])
                sources['repositories'].append(source)
                state['repositories'].append(runtime)
                state.setdefault('pending_source_blockers', {}).pop(name, None)
                synced.append(name)
            except (WatchError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
                remaining.append(pending)
                state.setdefault('pending_source_blockers', {})[name] = str(error)
                blockers.append({'repository': name, 'reason': str(error)})
        state['source_blockers'] = [
            {'repository': item['repository'], 'reason': item['blocker']}
            for item in state['repositories'] if item.get('blocker')]
        state['source_blockers'].extend(
            {'repository': name, 'reason': reason}
            for name, reason in sorted(state.get('pending_source_blockers', {}).items()))
        sources['pending_source_additions'] = remaining
        self.save_pair(sources, state)
        return {'synced': synced, 'blockers': blockers, 'pending_sources': len(remaining)}

    def save_pair(self, sources, state):
        # Intent file makes a crash between the two renames replayable.
        transaction = self.data_dir / '.checkpoint-transaction.json'
        atomic_json(transaction, {'sources': sources, 'state': state})
        atomic_json(self.data_dir / 'sources.json', sources)
        atomic_json(self.data_dir / 'state.json', state)
        transaction.unlink()
        fsync_dir(self.data_dir)

    def recover_transaction(self):
        transaction = self.data_dir / '.checkpoint-transaction.json'
        if transaction.exists():
            value = read_json(transaction)
            require(isinstance(value, dict) and set(value) == {'sources', 'state'},
                    'malformed checkpoint transaction; manual recovery required')
            with tempfile.TemporaryDirectory(prefix='firmware-watch-recovery-') as temporary:
                atomic_json(Path(temporary) / 'sources.json', value['sources'])
                atomic_json(Path(temporary) / 'state.json', value['state'])
                atomic_bytes(Path(temporary) / 'reviews.jsonl',
                             (self.data_dir / 'reviews.jsonl').read_bytes())
                for name in ('migration-report.json', 'legacy-issue-152.json'):
                    archived = self.data_dir / name
                    if archived.exists():
                        atomic_bytes(Path(temporary) / name, archived.read_bytes())
                Watch(temporary, self.cache_dir).load()
            atomic_json(self.data_dir / 'sources.json', value['sources'])
            atomic_json(self.data_dir / 'state.json', value['state'])
            transaction.unlink()
            fsync_dir(self.data_dir)

    @staticmethod
    def update_cursor(sources, state, records):
        # Record count and prefix digest make the fairness cache recoverable if
        # the durable append completed before its state write.
        imported_count = sum('provenance' in r for r in records)
        processed = state.get('round_robin_processed_records', imported_count)
        require(type(processed) is int and imported_count <= processed <= len(records),
                'invalid round-robin journal cursor')
        digest = hashlib.sha256(json_bytes(records[:processed])).hexdigest()
        if 'round_robin_journal_prefix_sha256' in state:
            require(state['round_robin_journal_prefix_sha256'] == digest,
                    'round-robin journal prefix changed; manual recovery required')
        appended = [r for r in records[processed:] if 'provenance' not in r]
        if appended:
            names = [s['repository'] for s in sources['repositories']]
            state['round_robin_next_repository_index'] = (names.index(appended[-1]['repository']) + 1) % len(names)
        state['round_robin_processed_records'] = len(records)
        state['round_robin_journal_prefix_sha256'] = hashlib.sha256(json_bytes(records)).hexdigest()

    def checkpoint(self):
        self.recover_tail()
        self.recover_transaction()
        sources, state, records = self.load()
        self.update_cursor(sources, state, records)
        completed = {k for k, v in effective_reviews(records).items() if v['disposition'] in TERMINAL}
        advanced, blockers = [], []
        for source in sources['repositories']:
            repository = source['repository']
            runtime = self.runtime(state, repository)
            try:
                require(not runtime.get('blocker'), runtime.get('blocker'))
                self.check_cache(source, runtime)
                for branch, target in sorted(runtime['pinned_recent_targets'].items()):
                    frontier = runtime['recent_frontiers'][branch]
                    interval = self.rev_list(repository, [target], [frontier])
                    if all((repository, commit) in completed for commit in interval):
                        observed = runtime.get('observed_tips', {}).get(branch)
                        if observed:
                            require(target in self.rev_list(repository, [observed]),
                                    'observed tip rewrote pinned target')
                            runtime['pinned_recent_targets'][branch] = observed
                        runtime['recent_frontiers'][branch] = target
                        advanced.append({'repository': repository, 'branch': branch,
                                         'frontier': target,
                                         'pinned_target': runtime['pinned_recent_targets'][branch]})
            except (WatchError, OSError, subprocess.SubprocessError) as error:
                blockers.append({'repository': repository, 'reason': str(error)})
        atomic_json(self.data_dir / 'state.json', state)
        result = self.summary()
        state['current_summary'] = result
        atomic_json(self.data_dir / 'state.json', state)
        atomic_json(self.data_dir / 'summary.json', result)
        return {'advanced': advanced, 'blockers': blockers, 'summary': result}

    def validate_record(self, record, sources, state, effective):
        validate_review_structure(record, sources['destination_repo'])
        key = review_key(record)
        repository, commit = key
        source = next((s for s in sources['repositories'] if s['repository'] == repository), None)
        require(source is not None, 'unregistered source')
        runtime = self.runtime(state, repository)
        require(not runtime.get('blocker'), runtime.get('blocker'))
        inventories = self.inventories(source, runtime)
        existing = effective.get(key)
        if existing and existing['disposition'] in TERMINAL:
            require(review_content(existing) == review_content(record), 'conflicting terminal record')
            return False
        require(commit in inventories[record['queue']], 'commit does not belong to the frozen queue')
        actual = self.metadata(source, runtime, commit, record['queue'])
        for field in ('parents', 'branches', 'commit_title', 'changed_paths'):
            expected, supplied = actual[field], record[field]
            if field in ('branches', 'changed_paths'):
                expected, supplied = sorted(expected), sorted(supplied)
            require(expected == supplied, field + ' differs from actual source commit')
        return True

    def record(self, input_path):
        self.recover_tail()
        self.recover_transaction()
        sources, state, records = self.load()
        payload = read_json(input_path)
        additions = payload.get('records', [payload]) if isinstance(payload, dict) else payload
        require(isinstance(additions, list) and additions, 'input must contain one or more records')
        effective = effective_reviews(records)
        accepted = []
        for original in additions:
            record = copy.deepcopy(original)
            require('provenance' not in record, 'new records must not supply imported provenance')
            if self.validate_record(record, sources, state, effective):
                # An identical retry of a pending assessment is idempotent too.
                previous = effective.get(review_key(record))
                if previous and review_content(previous) == review_content(record):
                    continue
                accepted.append(record)
                effective[review_key(record)] = record
        if accepted:
            data = b''.join((json.dumps(r, sort_keys=True, ensure_ascii=False) + '\n').encode()
                            for r in accepted)
            with (self.data_dir / 'reviews.jsonl').open('ab') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            self.update_cursor(sources, state, records + accepted)
            atomic_json(self.data_dir / 'state.json', state)
        # If a crash happened after the durable append, an identical retry rebuilds
        # checkpoints without appending or claiming duplicate completion.
        result = self.checkpoint()
        result['appended'] = len(accepted)
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', default='data/firmware-watch')
    parser.add_argument('--cache-dir', default='build/firmware-watch')
    parser.add_argument('--lease-dir', help='absolute run-lease directory shared by every worktree')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('migrate').add_argument('--snapshot', required=True)
    commands.add_parser('validate')
    commands.add_parser('summary')
    commands.add_parser('sync').add_argument('--repository')
    commands.add_parser('queue').add_argument('--limit', type=int, default=50)
    commands.add_parser('record').add_argument('--input', required=True)
    commands.add_parser('checkpoint')
    lease = commands.add_parser('lease')
    lease.add_argument('action', choices=('acquire', 'release'))
    lease.add_argument('--owner', required=True)
    args = parser.parse_args(argv)
    try:
        watch = Watch(args.data_dir, args.cache_dir, lease_dir=args.lease_dir)
        with writer_lock(args.data_dir):
            watch.recover_transaction()
            if args.command == 'lease':
                result = watch.lease(args.action, args.owner)
            elif args.command == 'migrate':
                result = watch.migrate(args.snapshot)
            elif args.command == 'sync':
                result = watch.sync(args.repository)
            elif args.command == 'queue':
                result = watch.queue(args.limit)
            elif args.command == 'record':
                result = watch.record(args.input)
            else:
                result = getattr(watch, args.command)()
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    except (WatchError, KeyError, TypeError, StopIteration, OSError,
            subprocess.SubprocessError, json.JSONDecodeError) as error:
        print('firmware-watch: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
