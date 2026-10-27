#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Semantic host coverage. Reports are diagnostic evidence, never release inputs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
import runpy
import unittest

SCHEMA = 1
REQUIRED_OUTPUTS = {'build/felucca.dis': None, 'build/emu/felucca.wasm': None,
                    'build/host/asan/fuzz_ed': 'asan_fuzz_ed', 'build/host/phys_ref': 'phys_ref',
                    'build/host/regress': 'regression', 'build/host/regress_os': 'regression'}
PRODUCERS = {'tests/target_budget.py': {'target-budget'},
             'tests/install_test.py': {'js-synthetic', 'built-package-parity', 'official-v15'},
             'tests/fx_rest_test.py': {'fx-rest'},
             'tests/chorus_depth_test.py': {'chorus-native', 'chorus-sanitizer'},
             'tests/send_gain_test.py': {'sends-native', 'sends-sanitizer'},
             'tests/motion_sparse_test.py': {'motion-sparse', 'motion-sparse-sanitizer'},
             'tests/audio_transition_test.py': {'audio-transitions', 'transitions-sanitizer'},
             'tests/regress_counter_test.py': {'counter-injection'},
             'tests/macro_device_pack_test.py': {'macro-pack', 'macro-webapp-parser'},
             'web/emu/partition_test.sh': {'native-partitions', 'wasm-partitions'}}
ROOT = Path(__file__).resolve().parents[1]
CONFIG_KEYS = ('CC', 'CXX', 'SANITIZE', 'TSAN', 'JOBS', 'TEST_JOBS', 'DAISYSP',
               'GOLDEN_UPDATE', 'BUDGET_UPDATE', 'VERSION', 'EMU_OPT', 'EMU_CFLAGS', 'EMU_PREVIEW', 'LCD_BAUD',
               'JIELI_TOOLCHAIN', 'AC79_SDK', 'UI_SCREEN_DIR', 'MENU_JSON', 'TRACKS')
SAN_FLAGS = ['-O1', '-g', '-fsanitize=address,undefined',
             '-fno-sanitize=signed-integer-overflow,shift,bounds,object-size,pointer-overflow',
             '-fno-sanitize-recover=undefined', '-w']


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('duplicate coverage key: ' + key)
            value[key] = item
        return value
    return json.loads(Path(path).read_text(), object_pairs_hook=unique)


def atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(data, sort_keys=True, indent=2) + '\n')
    temporary.replace(path)


def snapshot(root, env):
    root = Path(root)
    if (root / '.git').exists():
        names = subprocess.check_output(['git', '-C', str(root), 'ls-files', '--cached',
                                         '--others', '--exclude-standard', '-z']).decode().split('\0')
        files = {name: digest(root / name) if (root / name).is_file() else None
                 for name in sorted(set(names)) if name}
        engine = root / 'firmware/engines'
        pin = subprocess.check_output(['git', '-C', str(engine), 'rev-parse', 'HEAD'], text=True).strip()
        committed = subprocess.check_output(['git', '-C', str(root), 'ls-tree', 'HEAD', 'firmware/engines'], text=True).split()
        dirty = subprocess.check_output(['git', '-C', str(engine), 'status', '--porcelain'], text=True)
        if dirty or len(committed) != 4 or pin != committed[2]:
            raise ValueError('coverage requires the committed clean Engines checkout')
        revision = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
        dirty = bool(subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain'], text=True))
        source_kind = 'git'
    else:
        # Reuse the release source verifier, including extra-file/mode/symlink
        # rejection. Absence of Git is never an unverified transcript fallback.
        import source_archive
        metadata = source_archive.verify_tree(root)
        files = {name: entry['sha256'] for name, entry in metadata['files'].items()}
        files[source_archive.MANIFEST] = digest(root / source_archive.MANIFEST)
        revision, pin = metadata['firmware_revision'], metadata['engines']['revision']
        dirty, source_kind = False, 'verified-archive'
    generated = root / 'build/gen'
    files.update({str(p.relative_to(root)): digest(p) for p in sorted(generated.glob('*')) if p.is_file()})
    configuration = {k: env.get(k) for k in sorted(set(CONFIG_KEYS) |
                     {k for k in env if k.startswith('FELUCCA_') and not k.startswith('FELUCCA_COVERAGE_')})}
    # run_tests.sh exports this established default before entering the scheduler.
    configuration['AC79_SDK'] = env.get('AC79_SDK') or str(Path.home() / 'fw-AC79_AIoT_SDK')
    return dict(revision=revision, dirty=dirty, source_kind=source_kind,
                inputs=files, engines=pin,
                configuration=configuration,
                platform=platform.system(), architecture=platform.machine())


def host_config(env=None, probe=True):
    env = dict(os.environ if env is None else env)
    cc = shlex.split(env.get('CC', 'cc'))
    common = ['-O1', '-Wall', '-Wno-unused-function', '-Ibuild/gen']
    novec = ['-fno-vectorize', '-fno-slp-vectorize']
    if not probe:
        return dict(requested=cc, common=common, novec=novec, compiler=None)
    probe = subprocess.run(cc + common + novec + ['-x', 'c', '-c', '-o', os.devnull, '-'],
                           input='int x;', text=True, capture_output=True, env=env)
    if probe.returncode:
        novec = ['-fno-tree-vectorize', '-fno-tree-slp-vectorize']
    return dict(requested=cc, common=common, novec=novec,
                compiler=subprocess.check_output(cc + ['--version'], text=True, env=env).strip())


def baseline_config(configuration, root=ROOT, env=None):
    return subprocess.check_output([sys.executable, str(Path(root) / 'tests/cpu_baseline.py'),
                                    *configuration['requested'], *configuration['common']],
                                   text=True, env=env).splitlines()


def command_policy(argv):
    outcomes = set().union(*(PRODUCERS.get(x, set()) for x in argv))
    if argv and Path(argv[0]).name in ('regress', 'regress_os', 'regress_cpu2_0', 'regress_c1'):
        outcomes.add('regression')
    offset = 2 if len(argv) > 2 and argv[1] == '-O' else 1
    python = bool(argv and Path(argv[0]).name.startswith('python') and
                  len(argv) > offset and argv[offset].endswith('.py'))
    return sorted(outcomes), python, offset


def shard_plan(plan, count=2):
    """Partition dependency-connected components; each unit has one owner."""
    if count != 2:
        raise ValueError('host coverage supports exactly two shards')
    parents = {u['name']: u['name'] for u in plan}
    def owner(name):
        while parents[name] != name:
            name = parents[name]
        return name
    for unit in plan:
        for dependency in unit['dependencies']:
            parents[owner(unit['name'])] = owner(dependency)
    components = {}
    for unit in plan:
        components.setdefault(owner(unit['name']), []).append(unit['name'])
    groups = [set() for _ in range(count)]
    for names in sorted(components.values(), key=lambda names: (-len(names), names[0])):
        groups[min(range(count), key=lambda i: (len(groups[i]), i))].update(names)
    return [[u['name'] for u in plan if u['name'] in names] for names in groups]


def select_plan(plan, scope):
    if scope['kind'] == 'full':
        return plan
    if scope['kind'] == 'shard':
        names = set(shard_plan(plan, scope['count'])[scope['index'] - 1])
    elif scope['kind'] == 'focused':
        names = set(scope['selected'])
        by_name = {u['name']: u for u in plan}
        if not names or names - by_name.keys():
            raise ValueError('unknown or empty focused host unit selection')
        pending = list(names)
        while pending:
            for dependency in by_name[pending.pop()]['dependencies']:
                if dependency not in names:
                    names.add(dependency)
                    pending.append(dependency)
    else:
        raise ValueError('unknown host coverage scope')
    return [u for u in plan if u['name'] in names]


def write_event(kind, **data):
    directory = os.environ.get('FELUCCA_COVERAGE_UNIT')
    if directory:
        atomic(Path(directory) / (uuid.uuid4().hex + '.json'),
               dict(schema=SCHEMA, run_id=os.environ['FELUCCA_COVERAGE_ID'], kind=kind, **data))


class Producer:
    """One top-level producer owns one report; nested fixtures cannot inherit it."""
    def __init__(self):
        self.path = os.environ.pop('FELUCCA_COVERAGE_CHILD', None)
        self.rows = []

    def outcome(self, name, status='passed', reason=None, **details):
        self.rows.append(dict(name=name, status=status, reason=reason, details=details))
        if self.path:
            atomic(self.path, dict(schema=SCHEMA, outcomes=self.rows))


def compiler_main(mapping, alias, argv):
    requested = read_json(mapping)[alias]
    executable = requested[0]
    args = requested + argv
    probe = '--version' in argv or '-E' in argv or ('-o' in argv and argv[argv.index('-o') + 1] == os.devnull)
    write_event('probe' if probe else 'compiler', argv=args, executable=executable, pid=os.getpid())
    os.execv(executable, args)


def compiler_environment(env, directory):
    """Private passthrough executables preserve argv, exec signals and return codes."""
    directory = Path(directory)
    directory.mkdir(parents=True)
    original = dict(env)
    mapping = {}
    for alias in ('cc', 'clang', 'gcc', 'c++', 'clang++', 'g++'):
        if actual := shutil.which(alias, path=original.get('PATH')):
            mapping[alias] = [actual]
    # CC/cc would be the same file on the default macOS filesystem.
    for key, default in (('CC', 'cc'), ('CXX', 'c++')):
        words = shlex.split(original.get(key, default))
        if not words or not (actual := shutil.which(words[0], path=original.get('PATH'))):
            if key == 'CXX' and key not in original:
                continue  # Optional reference units keep their explicit missing-C++ skip.
            raise ValueError(f'coverage compiler not available: {key}')
        mapping["requested-" + key.lower()] = [actual, *words[1:]]
    path = directory / 'compilers.json'
    atomic(path, mapping)
    for alias in mapping:
        shim = directory / alias
        shim.write_text('#!' + sys.executable + '\nimport runpy,sys\nsys.argv = ' +
                        repr([str(Path(__file__).resolve()), 'compiler', str(path), alias]) +
                        ' + sys.argv[1:]\nrunpy.run_path(sys.argv[0], run_name="__main__")\n')
        shim.chmod(0o755)
    result = dict(env, CC=str(directory / 'requested-cc'),
                  PATH=str(directory) + os.pathsep + env.get('PATH', ''))
    if 'requested-cxx' in mapping:
        result['CXX'] = str(directory / 'requested-cxx')
    return result, mapping


def run_command(argv):
    """Record real child invocation; semantic producers additionally own outcomes."""
    producer = None
    required_outcomes, python_required, offset = command_policy(argv)
    if required_outcomes:
        producer = Path(os.environ['FELUCCA_COVERAGE_UNIT']) / (uuid.uuid4().hex + '.child')
    env = dict(os.environ)
    if producer:
        env['FELUCCA_COVERAGE_CHILD'] = str(producer)
    python_report = None
    command = argv
    if python_required:
        python_report = Path(os.environ['FELUCCA_COVERAGE_UNIT']) / (uuid.uuid4().hex + '.python')
        env['FELUCCA_COVERAGE_PYTHON'] = str(python_report)
        command = argv[:offset] + [str(Path(__file__).resolve()), 'python-run'] + argv[offset:]
    result = subprocess.run(command, env=env)
    rows = None
    if producer and producer.is_file():
        rows = read_json(producer)
        producer.unlink()
    python_result = None
    if python_report and python_report.is_file():
        python_result = read_json(python_report)
        python_report.unlink()
    write_event('command', argv=argv, returncode=result.returncode, producer=rows,
                required_producer=producer is not None, python=python_result,
                required_python=python_required, expected_outcomes=required_outcomes)
    return result.returncode if result.returncode >= 0 else 128 - result.returncode


def python_run(argv):
    path = os.environ.pop('FELUCCA_COVERAGE_PYTHON')
    original = unittest.TextTestRunner.run
    depth, results = 0, []

    def run(runner, test):
        nonlocal depth
        depth += 1
        try:
            result = original(runner, test)
            if depth == 1:
                results.append(dict(tests=result.testsRun,
                                    skipped=[dict(test=t.id(), reason=why) for t, why in result.skipped],
                                    successful=result.wasSuccessful()))
            return result
        finally:
            depth -= 1

    unittest.TextTestRunner.run = run
    sys.argv = argv
    sys.path.insert(0, str(Path(argv[0]).resolve().parent))
    try:
        runpy.run_path(argv[0], run_name='__main__')
    finally:
        atomic(path, dict(schema=SCHEMA, unittest=results))


def requirements(needs, env):
    """Applicability is source/config based; installation only affects availability."""
    missing = []
    for need in needs:
        if need not in ('assets', 'pillow', 'sanitizer', 'node', 'emcc', 'macro-assets'):
            raise ValueError('unknown coverage prerequisite: ' + need)
        if need == 'assets' and not (ROOT / 'build/gen/felucca_tables.h').is_file():
            missing.append('generated-assets-missing')
        elif need == 'pillow':
            if subprocess.run([sys.executable, '-c', 'import PIL'], capture_output=True).returncode:
                missing.append('pillow-unavailable')
        elif need == 'sanitizer':
            if env.get('SANITIZE', '1') == '0':
                missing.append('sanitizer-disabled')
            else:
                with tempfile.TemporaryDirectory() as temporary:
                    args = shlex.split(env.get('CC', 'cc')) + SAN_FLAGS + ['-x', 'c', '-o', temporary + '/probe', '-']
                    r = subprocess.run(args, input='int main(void){return 0;}\n', text=True, capture_output=True)
                    if r.returncode or subprocess.run([temporary + '/probe'], capture_output=True).returncode:
                        missing.append('sanitizer-unavailable')
        elif need in ('node', 'emcc') and not shutil.which(need, path=env.get('PATH')):
            missing.append(need + '-unavailable')
        elif need == 'macro-assets' and not (ROOT / 'build/gen/felucca_braids.h').is_file():
            missing.append('macro-assets-missing')
    return missing


def selected_engines(root, env):
    import profile
    return [e['id'] for e in profile.validate_selection(Path(root), env.get('FELUCCA_PROFILE', 'standard'))[2]]


class Coverage:
    def __init__(self, root, env):
        self.root, self.env = Path(root), dict(env)
        self.run_id = env.get('FELUCCA_COVERAGE_ID') or uuid.uuid4().hex
        self.path = Path(env['FELUCCA_COVERAGE_REPORT']).resolve() if env.get('FELUCCA_COVERAGE_REPORT') else None
        if self.path:
            try:
                previous = read_json(self.path) if self.path.exists() else {}
            except (ValueError, OSError):
                previous = {}
            atomic(self.path, dict(schema=SCHEMA, run_id=self.run_id, status='incomplete'))
            if isinstance(previous, dict) and previous.get('run_id') == self.run_id:
                raise ValueError('coverage invocation identity must be fresh')
        self.before = snapshot(root, env)
        self.engine_ids = selected_engines(self.root, env)
        self.compiler = host_config(env)
        self.baselines = baseline_config(self.compiler, self.root, env=env)
        self.temporary = tempfile.TemporaryDirectory(prefix='felucca-coverage-')
        self.worker_env, self.compiler_map = compiler_environment(env, Path(self.temporary.name) / 'bin')
        self.compiler_hashes = {argv[0]: digest(argv[0]) for argv in self.compiler_map.values()}
        self.worker_env['FELUCCA_COVERAGE_ID'] = self.run_id

    def finish(self, summary, logs):
        self.path = self.path or logs / 'coverage.json'
        try:
            after = snapshot(self.root, self.env)
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            after = dict(error=str(error))
        data = dict(schema=SCHEMA, run_id=self.run_id, status='incomplete', before=self.before,
                    after=after, compiler=self.compiler,
                    compiler_map=self.compiler_map, summary=summary, units=[])
        data['compiler_hashes'] = self.compiler_hashes
        data['baselines'] = self.baselines
        data['engine_ids'] = self.engine_ids
        data['checkout_root'] = str(self.root.resolve())
        data['scope'] = summary.get('scope', dict(kind='full'))
        data['outputs'] = {p: dict(sha256=digest(self.root / p), bytes=(self.root / p).stat().st_size)
                           for p in ('build/felucca.dis', 'build/emu/felucca.wasm', 'build/host/asan/fuzz_ed',
                                     'build/host/phys_ref', 'build/host/regress', 'build/host/regress_os')
                           if (self.root / p).is_file()}
        if data['scope']['kind'] == 'shard':
            # A receipt remains verifiable after artifact download into another checkout.
            names = {u['name'] for u in summary['units']}
            data['outputs'] = {p: item for p, item in data['outputs'].items()
                               if REQUIRED_OUTPUTS[p] is None or REQUIRED_OUTPUTS[p] in names}
            for p in data['outputs']:
                destination = logs / 'outputs' / p
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.root / p, destination)
        for unit in summary['units']:
            events = [read_json(p) for p in sorted((logs / (unit['name'] + '.coverage')).glob('*.json'))]
            data['units'].append(dict(name=unit['name'], events=events, log=unit['log'],
                                      log_sha256=digest(logs / unit['log'])))
        data['logs_root'] = str(logs.resolve())
        data['stage_logs'] = {name: digest(logs / name) for name in
                              ('preflight.log', 'plan.stdout.log', 'plan.stderr.log') if (logs / name).is_file()}
        data['plan_sha256'] = digest(logs / 'plan.stdout.log') if (logs / 'plan.stdout.log').exists() else None
        if data['before'] != data['after']:
            summary['status'] = 'failed'
        data['status'] = 'complete' if summary['status'] == 'passed' and data['before'] == data['after'] else 'incomplete'
        atomic(self.path, data)
        if data['scope']['kind'] == 'shard' and self.path != logs / 'coverage.json':
            atomic(logs / 'coverage.json', data)
        summary['coverage'] = dict(path=str(self.path), run_id=self.run_id)
        self.temporary.cleanup()
        return data['before'] == data['after']


def verify(path, run_id, root=ROOT):
    return _verify(path, run_id, root)


def _verification_environment():
    # Verification observes an existing receipt; its compiler/plan probes do not
    # belong to a calling test unit. Keep compiler shims and flags intact, but
    # prevent every shim in a nested chain from publishing observer events.
    return {key: value for key, value in os.environ.items()
            if not key.startswith('FELUCCA_COVERAGE_')}


def _verify(path, run_id, root=ROOT, shard=False):
    probe_env = _verification_environment()

    def require(condition, message):
        if not condition:
            raise ValueError('incomplete test coverage: ' + message)

    d = read_json(path)
    scope = d.get('scope', dict(kind='full'))
    require(scope.get('kind') == ('shard' if shard else 'full'), 'partial scope cannot establish full coverage')
    require(d.get('schema') == SCHEMA and d.get('run_id') == run_id and bool(run_id), 'schema or run identity')
    require(not any(key in os.environ for key in ('GOLDEN_UPDATE', 'BUDGET_UPDATE')),
            'baseline update mode is not comparison coverage')
    require(d.get('status') == 'complete', 'run not complete')
    normalize = (lambda value: portable(value, d.get('checkout_root', ''), root)) if shard else (lambda value: value)
    require(d.get('before') == d.get('after') and normalize(d.get('before')) == snapshot(root, os.environ),
            'source/configuration changed or stale')
    require(normalize(d['compiler']) == host_config(probe_env), 'host compiler/configuration changed')
    require(d['baselines'] == baseline_config(normalize(d['compiler']), root, env=probe_env), 'CPU baseline selection changed')
    require(d['engine_ids'] == selected_engines(root, os.environ), 'profile applicability changed')
    if shard:
        with tempfile.TemporaryDirectory() as temporary:
            _, mapping = compiler_environment(probe_env, Path(temporary) / 'bin')
            require(compiler_identity(d['compiler_map'], d['compiler_hashes'], normalize) ==
                    compiler_identity(mapping, {a[0]: digest(a[0]) for a in mapping.values()}),
                    'compiler executable changed or absent')
    else:
        require(d['compiler_hashes'] and all(digest(p) == sha for p, sha in d['compiler_hashes'].items()),
                'compiler executable changed or absent')
    summary = d['summary']
    require(summary.get('scope', dict(kind='full')) == scope, 'runner scope mismatch')
    require(summary['status'] == 'passed' and summary.get('signal') is None, 'runner failed or cancelled')
    for stage in ('preflight', 'plan'):
        require(summary.get(stage, {}).get('status') == 'passed' and summary[stage].get('returncode') == 0,
                stage + ' not complete')
    logs = Path(path).resolve().parent if shard else Path(d['logs_root'])
    require(digest(logs / 'plan.stdout.log') == d['plan_sha256'], 'plan log changed')
    if shard:
        require(set(d.get('stage_logs', {})) == {'preflight.log', 'plan.stdout.log', 'plan.stderr.log'} and
                all(Path(name).name == name and digest(logs / name) == sha
                    for name, sha in d['stage_logs'].items()), 'preflight/plan log changed or absent')
    names = [u['name'] for u in summary['units']]
    require(names and len(names) == len(set(names)), 'missing/duplicate units')
    require(names == [u['name'] for u in d['units']], 'unit evidence mismatch')
    expected = subprocess.check_output(['sh', str(Path(root) / 'tests/run_tests.sh'), '--plan'],
                                       cwd=root, text=True, env=probe_env)
    require(hashlib.sha256(expected.encode()).hexdigest() == d['plan_sha256'], 'source plan does not match evidence')
    expected_lines = expected.splitlines()
    if shard:
        selected = select_plan([dict(name=line.split('\t')[0], dependencies=line.split('\t')[1].split())
                                for line in expected_lines], scope)
        selected_names = {u['name'] for u in selected}
        expected_lines = [line for line in expected_lines if line.split('\t')[0] in selected_names]
    require([line.split('\t')[0] for line in expected_lines] == names, 'expected unit absent')
    for line, unit in zip(expected_lines, summary['units']):
        fields = line.split('\t')
        metadata = json.loads(fields.pop().split('=', 1)[1])
        require(unit['dependencies'] == fields[1].split() and unit['command'] == fields[2:] and
                unit['needs'] == metadata['needs'] and unit['capabilities'] == metadata['capabilities'] and
                unit.get('producers', []) == metadata.get('producers', []),
                unit['name'] + ': declared plan metadata changed')
    required_outputs = {p for p, owner in REQUIRED_OUTPUTS.items() if not shard or owner is None or owner in names}
    require(set(d['outputs']) == required_outputs, 'required outputs absent')
    output_root = logs / 'outputs' if shard else Path(root)
    require(all(item['bytes'] > 0 and (output_root / p).stat().st_size == item['bytes'] and
                digest(output_root / p) == item['sha256'] for p, item in d['outputs'].items()),
            'required output empty, stale or changed')
    for unit, evidence in zip(summary['units'], d['units']):
        name = unit['name']
        require(Path(unit['log']).name == unit['log'] and evidence['log'] == unit['log'],
                name + ': invalid log identity')
        require(digest(logs / unit['log']) == evidence['log_sha256'], name + ': log changed')
        if unit['status'] == 'not_applicable':
            require(not evidence['events'] and unit.get('returncode') is None, name + ': excluded unit executed')
            require(name in ('tsan', 'macro', 'asan_macro') and unit.get('reason') in
                    ('not-requested', 'profile-excluded'), name + ': undeclared exclusion')
            require((name == 'tsan' and not os.environ.get('TSAN') and unit['reason'] == 'not-requested') or
                    (name in ('macro', 'asan_macro') and 14 not in d['engine_ids'] and unit['reason'] == 'profile-excluded'),
                    name + ': wrong applicability')
            continue
        require(unit['status'] == 'passed' and unit.get('returncode') == 0 and unit.get('reason') is None,
                name + ': required unit did not pass')
        events = evidence['events']
        require(events and all(e.get('schema') == SCHEMA and e.get('run_id') == run_id for e in events),
                name + ': no bound execution evidence')
        require(any(e['kind'] == 'command' or (name == 'hostsim' and e['kind'] == 'compiler') for e in events),
                name + ': no actual command')
        # Obligations come from the source plan, never from whichever events
        # happen to remain in the report. A sibling command cannot cover a lost child.
        for producer in unit.get('producers', []):
            matches = [e for e in events if e['kind'] == 'command' and
                       (producer in e['argv'] if producer in PRODUCERS else
                        bool(e['argv']) and Path(e['argv'][0]).name == producer)]
            require(len(matches) == 1, name + ': required child producer absent or duplicated: ' + producer)
        for event in events:
            require(event['kind'] in ('command', 'compiler', 'probe', 'outcome'), name + ': unknown event')
            if event['kind'] in ('compiler', 'probe'):
                require(bool(event['argv']) and event['argv'][0] == event['executable'], name + ': compiler identity')
                require(event['executable'] in d['compiler_hashes'], name + ': unbound compiler executable')
            elif event['kind'] == 'command':
                require(event['returncode'] == 0, name + ': child failed')
                outcomes, python_required, _ = command_policy(event['argv'])
                require(event['required_python'] == python_required and
                        event['required_producer'] == bool(outcomes) and event['expected_outcomes'] == outcomes,
                        name + ': child contract changed')
                if python_required:
                    require(event['python'] and event['python'].get('schema') == SCHEMA, name + ': child completion absent')
                    for result in event['python']['unittest']:
                        require(type(result['tests']) is int and result['tests'] > 0 and
                                result['successful'] is True and isinstance(result['skipped'], list) and
                                not result['skipped'], name + ': unittest empty/skipped/failed')
                if outcomes:
                    producer = event['producer']
                    require(producer and producer.get('schema') == SCHEMA and producer.get('outcomes'),
                            name + ': semantic child completion absent')
                    require(sorted(o['name'] for o in producer['outcomes']) == event['expected_outcomes'],
                            name + ': missing/duplicate/unknown child capability')
                    for outcome in producer['outcomes']:
                        require((outcome['status'] == 'passed' and outcome['reason'] is None) or
                                (outcome['name'] == 'official-v15' and outcome['status'] == 'skipped' and
                                 outcome['reason'] == 'proprietary-fixture-absent') or
                                (outcome['name'] == 'macro-webapp-parser' and outcome['status'] == 'not_applicable' and
                                 outcome['reason'] == 'not-requested' and
                                 not any(a == '--webapp' or a.startswith('--webapp=') for a in event['argv'])),
                                name + ': unapproved semantic skip')
                        if outcome['name'] == 'regression':
                            cpu = outcome['details']
                            require(len(event['argv']) == 3 and cpu['baseline'] == event['argv'][2],
                                    name + ': baseline does not match actual invocation')
                            require(0 <= cpu['available'] <= cpu['total'] and cpu['total'] > 0,
                                    name + ': invalid counter coverage')
                            require(cpu['missing_entries'] == 0, name + ': available CPU baseline lacks entries')
                            if cpu['cpu_status'] == 'skipped':
                                require((cpu['cpu_reason'] == 'counter-unavailable' and cpu['available'] < cpu['total']) or
                                        (cpu['cpu_reason'] == 'baseline-unavailable' and cpu['baseline'] == '-'),
                                        name + ': undeclared whole CPU skip')
                            elif cpu['cpu_status'] == 'not_applicable':
                                require(cpu['cpu_reason'] == 'c1-host-unqualified' and Path(event['argv'][0]).name == 'regress_c1',
                                        name + ': undeclared CPU exclusion')
                            else:
                                require(cpu['cpu_status'] == 'passed' and cpu['cpu_reason'] == '' and
                                        cpu['available'] == cpu['total'],
                                        name + ': incomplete CPU comparison')
            else:
                require(event['status'] == 'passed' and event.get('reason') is None,
                        name + ': unapproved conditional skip/reason')
        for capability in unit.get('capabilities', []):
            require(sum(e['kind'] == 'outcome' and e['name'] == capability for e in events) == 1,
                    name + ': missing capability ' + capability)
        require(all(e['name'] in unit['capabilities'] for e in events if e['kind'] == 'outcome'),
                name + ': undeclared capability')
        if name == 'regression':
            for binary, flags in (('regress', ['-O2']), ('regress_os', ['-Os', *d['compiler']['novec']]),
                                  ('regress_cpu2_0', ['-O2', '-DFELUCCA_CPU2=0']),
                                  ('regress_c1', ['-O2', '-DC1_HOST', '-pthread'])):
                require(any(e['kind'] == 'compiler' and 'tests/regress.c' in e['argv'] and
                            '-o' in e['argv'] and Path(e['argv'][e['argv'].index('-o') + 1]).name == binary and
                            all(flag in e['argv'] for flag in flags) for e in events),
                        name + ': effective compiler argv absent for ' + binary)
                baseline = d['baselines'][1 if binary == 'regress_os' else 0]
                baseline = baseline if (Path(root) / baseline).is_file() and binary != 'regress_c1' else '-'
                require(any(e['kind'] == 'command' and Path(e['argv'][0]).name == binary and
                            e['argv'][2] == baseline for e in events), name + ': wrong selected baseline for ' + binary)
    return d


def portable(value, old_root, root):
    """Relocate only the recorded checkout prefix; all semantic values stay exact."""
    if not old_root or not Path(old_root).is_absolute():
        raise ValueError('coverage receipt lacks checkout identity')
    if isinstance(value, str):
        return value.replace(old_root + '/', str(Path(root).resolve()) + '/') if old_root != str(root) else value
    if isinstance(value, list):
        return [portable(v, old_root, root) for v in value]
    if isinstance(value, dict):
        return {k: portable(v, old_root, root) for k, v in value.items()}
    return value


def compiler_identity(mapping, hashes, normalize=lambda value: value):
    if not mapping or not hashes or any(argv[0] not in hashes for argv in mapping.values()):
        raise ValueError('incomplete compiler identity')
    return {alias: dict(executable=normalize(argv[0]), arguments=normalize(argv[1:]), sha256=hashes[argv[0]])
            for alias, argv in mapping.items()}


def verify_shards(paths, cohort, root=ROOT):
    """Require two independent, complete receipts covering the source DAG once."""
    if len(paths) != 2 or not cohort:
        raise ValueError('coverage requires exactly two shard receipts and a cohort identity')
    reports, identities, indexes = [], set(), set()
    for directory in paths:
        path = Path(directory) / 'coverage.json'
        d = read_json(path)
        scope = d.get('scope', {})
        if (scope.get('kind') != 'shard' or scope.get('count') != 2 or
            type(scope.get('index')) is not int or scope['index'] not in (1, 2) or
            scope.get('cohort') != cohort or not d.get('run_id') or
            d['run_id'] in identities or scope['index'] in indexes):
            raise ValueError('missing, duplicate or stale shard identity')
        identities.add(d['run_id'])
        indexes.add(scope['index'])
        reports.append(_verify(path, d['run_id'], root, shard=True))
    names = [u['name'] for d in reports for u in d['units']]
    expected = subprocess.check_output(['sh', str(Path(root) / 'tests/run_tests.sh'), '--plan'],
                                       cwd=root, text=True, env=_verification_environment())
    if len(names) != len(set(names)) or set(names) != {line.split('\t')[0] for line in expected.splitlines()}:
        raise ValueError('missing or duplicate shard units')
    # Target/emulator inputs are prerequisites replicated independently on both runners.
    for output in (p for p, owner in REQUIRED_OUTPUTS.items() if owner is None):
        if reports[0]['outputs'][output] != reports[1]['outputs'][output]:
            raise ValueError('shard prerequisite output differs: ' + output)
    return dict(schema=SCHEMA, status='complete', cohort=cohort, units=names,
                runs=sorted(identities), shards=2)


def summarize(path):
    d = read_json(path)
    print('Structured host coverage: schema=%s status=%s invocation=%s revision=%s' %
          (d.get('schema'), d.get('status'), d.get('run_id'), d.get('before', {}).get('revision')))
    counts = d.get('summary', {}).get('unit_counts', {})
    print('Units: ' + ' '.join('%s=%s' % item for item in counts.items()))
    capabilities = dict(passed=0, skipped=0, failed=0)
    for evidence in d.get('units', []):
        for event in evidence['events']:
            rows = (event.get('producer') or {}).get('outcomes', [])
            if event['kind'] == 'outcome': rows = [event]
            for outcome in rows:
                capabilities[outcome['status']] = capabilities.get(outcome['status'], 0) + 1
                if outcome['status'] != 'passed' or outcome['name'] in ('regression', 'fx-rest'):
                    print(evidence['name'] + ': ' + json.dumps(outcome, sort_keys=True))
    print('Reported child/conditional capabilities: ' + ' '.join('%s=%s' % item for item in capabilities.items()))


def main():
    if sys.argv[1] == 'compiler':
        compiler_main(sys.argv[2], sys.argv[3], sys.argv[4:])
    elif sys.argv[1] == 'command':
        raise SystemExit(run_command(sys.argv[2:]))
    elif sys.argv[1] == 'python-run':
        python_run(sys.argv[2:])
    elif sys.argv[1] == 'outcome':
        write_event('outcome', name=sys.argv[2], status=sys.argv[3], reason=sys.argv[4] if len(sys.argv) > 4 else None)
    elif sys.argv[1] == 'plan-meta':
        print(json.dumps(dict(needs=sys.argv[2].split(), capabilities=sys.argv[3].split())))
    elif sys.argv[1] == 'partition-result':
        p = Producer()
        p.outcome('native-partitions')
        p.outcome('wasm-partitions', sys.argv[2], 'emcc-unavailable' if sys.argv[2] == 'skipped' else None)
    elif sys.argv[1] == 'host-config':
        c = host_config(probe='--plan' not in sys.argv)
        if '--shell' in sys.argv:
            # All caller-provided words are parsed once; the private CC shim owns them.
            print('CC=' + shlex.quote(shlex.join(c['requested'] + c['common'])))
            print('NOVEC=' + shlex.quote(' '.join(c['novec'])))
        else:
            print(json.dumps(c))
    elif sys.argv[1] == 'verify-shards':
        parser = argparse.ArgumentParser(description='Verify complete two-runner host coverage')
        parser.add_argument('--cohort', required=True)
        parser.add_argument('receipts', nargs='+', type=Path)
        args = parser.parse_args(sys.argv[2:])
        try:
            result = verify_shards(args.receipts, args.cohort)
        except (ValueError, OSError, KeyError, TypeError, IndexError, subprocess.SubprocessError) as error:
            parser.exit(1, 'incomplete shard coverage: ' + str(error) + '\n')
        print(json.dumps(result, sort_keys=True))
    elif sys.argv[1] == 'summary':
        summarize(sys.argv[2])


if __name__ == '__main__':
    main()
