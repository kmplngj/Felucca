#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Observed pi32v2 entry frames, without call-path or hardware stack-bank inference."""
import hashlib
import re

CODE = {'.text', '.ram_text', '.c1_text'}
REGISTER = re.compile(r'r(?:[0-9]|1[0-5])$')
SP_WRITE = re.compile(r'\b(?:sp|usp|ssp)\s*(?:(?:<<|>>|[+*/%&|^-])?=(?!=)|\+\+|--)'
                      r'|(?:--|\+\+)\s*(?:sp|usp|ssp)\b')


def registers(text):
    """Only ordinary C save/restore registers; context/stack-bank saves stay unscored."""
    result = []
    for item in text.strip('{} ').split(','):
        item = item.strip()
        span = re.fullmatch(r'r(\d+)-r(\d+)', item)
        if span:
            high, low = map(int, span.groups())
            if not 0 <= low <= high <= 15:
                raise ValueError('unsupported register range')
            result += ['r' + str(n) for n in range(low, high + 1)]
        elif item in ('rets', 'pc') or REGISTER.fullmatch(item):
            result.append(item)
        else:
            raise ValueError('unsupported register save/restore')
    if len(set(result)) != len(result):
        raise ValueError('duplicate register save/restore')
    return result


def inventory(symbols, listing):
    # Reuse the production parser/data-row contract, not another objdump dialect.
    from build import disassembly_rows
    rows, errors = disassembly_rows(listing, 'app')
    if errors:
        raise ValueError('; '.join(errors))
    instructions = []
    for row in rows:
        instructions.append(dict(address=int(row[1], 16), bytes=len(bytes.fromhex(row[2])),
                                 text=row[3].strip()))
    by_address = {}
    for row in instructions:
        if row['address'] in by_address:
            raise ValueError('duplicate disassembly address')
        by_address[row['address']] = row
    groups, unscored = {}, []
    for line in symbols.splitlines():
        p = line.split()
        function = 'F' in (p[1:-3] if len(p) >= 4 else p)
        if not function and not CODE.intersection(p):
            continue
        if 'd' in p or 'df' in p:
            continue
        if len(p) < 4 or not re.fullmatch('[0-9a-f]+', p[0], re.I) or not re.fullmatch('[0-9a-f]+', p[-2], re.I):
            raise ValueError('malformed code symbol: ' + line)
        address, size, section, name = int(p[0], 16), int(p[-2], 16), p[-3], p[-1]
        if not function or not size or section not in CODE:
            if not size or function:
                unscored.append(dict(name=name, address=address, size_bytes=size, section=section,
                                     reason='no sized C-function boundary', own_entry_bytes=None))
            continue
        groups.setdefault((address, size, section), []).append(name)
    functions = []
    for (address, size, section), names in sorted(groups.items()):
        if len(names) != len(set(names)):
            raise ValueError('duplicate function symbol')
        reasons, body = [], []
        if any(lo < address + size and address < lo + length and (lo, length) != (address, size)
               for lo, length, sec in groups if sec == section):
            reasons.append('overlapping function boundaries')
        end = address + size
        position = address
        while position < end:
            row = by_address.get(position)
            if row is None or position + row['bytes'] > end:
                reasons.append('incomplete listing or instruction crosses function boundary')
                break
            body.append(row)
            position += row['bytes']
        prologue, stack_operations, calls, branches = [], [], [], []
        local = saved = 0
        entry = True
        for row in body:
            text = row['text']
            allocation = re.fullmatch(r'sp \+= (-\d+)', text)
            push = re.fullmatch(r'\[--sp\] = (.+)', text)
            try:
                if entry and allocation:
                    amount = -int(allocation[1])
                    if amount % 4:
                        raise ValueError('unaligned entry allocation')
                    local += amount
                    prologue.append(row)
                elif entry and push:
                    regs = registers(push[1])
                    if 'pc' in regs:
                        raise ValueError('unsupported PC save')
                    saved += 4 * len(regs)
                    prologue.append(row)
                else:
                    entry = False
                    if allocation or push:
                        raise ValueError('stack allocation outside contiguous entry prologue')
                    release = re.fullmatch(r'sp \+= \+?(\d+)', text)
                    pop = re.fullmatch(r'(.+) = \[sp\+\+\]', text)
                    if release:
                        if int(release[1]) % 4:
                            raise ValueError('unaligned stack release')
                    elif pop:
                        registers(pop[1])
                    elif SP_WRITE.search(text):
                        raise ValueError('unsupported SP/stack-bank operation')
            except ValueError as error:
                reasons.append(str(error))
                entry = False
            if SP_WRITE.search(text):
                stack_operations.append(row)
            if re.match(r'^(?:\.\w+|\(bad\)|unknown(?:\b|_)|<)', text, re.I):
                reasons.append('undecoded instruction or inline data')
            if text.startswith('call'):
                direct = re.fullmatch(r'call (-?\d+)(?: <[^>]+>)?', text)
                indirect = re.fullmatch(r'call r(?:[0-9]|1[0-5])', text)
                if not direct and not indirect:
                    reasons.append('unsupported call form')
                calls.append(dict(address=row['address'], text=text,
                                  kind='direct' if direct else 'unresolved',
                                  target=row['address'] + row['bytes'] + int(direct[1]) if direct else None))
            branch = re.search(r'\bgoto (-?\d+)(?: <[^>]+>)?$', text)
            if branch:
                target = row['address'] + row['bytes'] + int(branch[1])
                if not address <= target < end:
                    branches.append(dict(address=row['address'], text=text, target=target,
                                         kind='outgoing branch; tail/frame release not inferred'))
            elif re.search(r'\bgoto\b', text) or (re.search(r'\bpc =', text)
                                                  and not re.fullmatch(r'pc = \[sp\+\+\]', text)):
                branches.append(dict(address=row['address'], text=text, target=None,
                                     kind='unresolved branch; frame release not inferred'))
        functions.append(dict(names=sorted(names), address=address, size_bytes=size, section=section,
                              status='unsupported' if reasons else 'observed entry',
                              reasons=sorted(set(reasons)),
                              own_entry_bytes=None if reasons else local + saved,
                              observed_entry_local_bytes=local, observed_entry_save_bytes=saved,
                              prologue=prologue, stack_operations=stack_operations,
                              calls=calls, outgoing_branches=branches))
    if not functions:
        raise ValueError('no sized functions in target symbol table')
    return dict(functions=functions, unscored_code_symbols=unscored,
                summary=dict(sized_function_records=len(functions),
                             unsupported_function_records=sum(f['own_entry_bytes'] is None for f in functions),
                             unscored_symbol_records=len(unscored),
                             unresolved_call_sites=sum(c['kind'] == 'unresolved' for f in functions for c in f['calls'])),
                scope='Sized C-function entry instructions only; unresolved and ASM boundaries remain explicit',
                limitations=['No transitive call closure, callback resolution, recursion or nesting bound',
                             'No hardware stack-bank, fault-context, live watermark, fit or spare-margin result',
                             'Zero-sized ASM/aliases and unsupported frame forms are not assigned zero bytes',
                             'Source ISR callback contracts remain owned by tools/size_fns.py'])


def evidence(report, report_bytes, symbols, listing):
    result = inventory(symbols, listing)
    result.update(kind='felucca-target-own-entry-frames', build_identity=report['build_identity'],
                  binding=dict(resource_report_sha256=hashlib.sha256(report_bytes).hexdigest(),
                               elf_sha256=report['artifact_sha256']['build/felucca.elf'],
                               listing_sha256=report['artifact_sha256']['build/felucca.dis'],
                               symbol_table_sha256=hashlib.sha256(symbols.encode()).hexdigest(),
                               configuration_sha256=report['configuration_sha256']),
                  stack_reservations=report['stack_reservations'])
    return result
