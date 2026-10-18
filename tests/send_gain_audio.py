#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
import hashlib,json,pathlib,subprocess,itertools,os,shlex
import numpy as np
import argparse
parser=argparse.ArgumentParser(description='Retain native send/MASTER WAVs and normalized residual metrics for an isolated FX source.')
parser.add_argument('--fx-source',type=pathlib.Path)
parser.add_argument('--out',type=pathlib.Path,required=True)
parser.add_argument('--compare',type=pathlib.Path,help='compare retained metrics and exact PCM/state against a baseline output')
parser.add_argument('--opt',choices=['O2','Os'],default='O2')
args=parser.parse_args()
root=pathlib.Path(__file__).resolve().parents[1]; base=root/'tests'; out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
source=args.fx_source or root/'firmware/src/fx.c'
(out/'fx.c').write_text(source.read_text())
variant=out.name
src=(out/'fx.c').read_text()
tap='    if (perf)\n        perf_pre'
assert src.count(tap)==1
instrumented='static int32_t experiment_dry[2][32];\n'+src.replace(tap,'    for (uint32_t j=0;j<n;j++) {experiment_dry[0][j]=mix_l[j];experiment_dry[1][j]=mix_r[j];}\n'+tap)
(out/'fx_instrumented.c').write_text(instrumented)
# fx.c quoted local perform include must resolve to firmware; keep a real source snapshot.
host=(root/'tests/hostsim.c').read_text().replace('#include "../firmware/src/fx.c"',f'#include "{out}/fx_instrumented.c"').replace('"../firmware/src/',f'"{root}/firmware/src/')
(out/'hostsim.c').write_text(host)
cc=shlex.split(os.environ.get('CC','cc'))
flags=['-'+args.opt]
if args.opt=='Os':
    novec=['-fno-vectorize','-fno-slp-vectorize']
    if subprocess.run(cc+novec+['-x','c','-c','-o',os.devnull,'-'],input='',text=True,capture_output=True).returncode:
        novec=['-fno-tree-vectorize','-fno-tree-slp-vectorize']
    flags+=novec
cmd=cc+flags+['-w','-I'+str(root/'build/gen'),'-I'+str(root/'firmware/src'),f'-DFX_TEST_HOSTSIM="{out}/hostsim.c"',str(base/'send_gain_audio.c'),'-lm','-o',str(out/'experiment')]
subprocess.run(cmd,check=True)
results={}
for chord,spread,bus,mode in itertools.product(range(2),range(2),(1,2,4,7),range(9)):
    scenario=f'{chord}-{spread}-{bus}-{mode}'; rows=[]
    for edit in (0,1):
        dest=out/f'{scenario}-{edit}';dest.mkdir(exist_ok=True)
        subprocess.run([str(out/'experiment'),str(dest),str(chord),str(spread),str(bus),str(mode),str(edit)],check=True)
        rows.append(np.fromfile(dest/'data.bin',dtype=np.int32).reshape(-1,7).astype(float))
    source_scale=np.sqrt(np.mean(rows[0][8192:,5]**2)); full_residual=rows[1]-rows[0]; residual=full_residual[8190:,:5]
    metrics=[]
    for k in range(5):
        r=residual[:,k]; spec=np.fft.rfft(r*np.hanning(len(r))); freq=np.fft.rfftfreq(len(r),1/44100)
        windows=np.lib.stride_tricks.sliding_window_view(full_residual[8064:,k],256)[::32]
        spectra=np.fft.rfft(windows*np.hanning(256),axis=1)
        local_hf=float(np.max(np.sqrt(np.sum(abs(spectra[:,47:])**2,axis=1)))/256/source_scale)
        metrics.append(dict(local_hf=local_hf,d1=float(np.max(np.abs(np.diff(r)))/source_scale),d2=float(np.max(np.abs(np.diff(r,2)))/source_scale),hf=float(np.sqrt(np.sum(abs(spec[freq>=8000])**2))/len(r)/source_scale)))
    results[scenario]=dict(scale=source_scale,metrics=metrics)
(out/'metrics.json').write_text(json.dumps(results,indent=2))
(out/'provenance.json').write_text(json.dumps(dict(source_sha256=hashlib.sha256(src.encode()).hexdigest(),core_sha256=hashlib.sha256((root/'firmware/src/core.h').read_bytes()).hexdigest(),compiler=subprocess.check_output(cc+['--version'],text=True).splitlines()[0],command=cmd,timeline='32768 frames, CTL32; edit at8192; modes full up/full down/63->64/alternating0-127 everyblock/one detent per512 frames',generated_sha256=hashlib.sha256((root/'build/gen/felucca_tables.h').read_bytes()).hexdigest()),indent=2))
print(variant,len(results),'native recording pairs written; source',hashlib.sha256(src.encode()).hexdigest())

if args.compare:
    baseline=args.compare.resolve()
    old=json.loads((baseline/'metrics.json').read_text())
    ratios={}
    for name in results:
        ratios[name]=[{q:results[name]['metrics'][k][q]/old[name]['metrics'][k][q] if old[name]['metrics'][k][q] else 1.0
                       for q in ['d1','d2','hf','local_hf']} for k in range(5)]
        for edit in (0,1):
            a=np.fromfile(baseline/f'{name}-{edit}/data.bin',dtype=np.int32).reshape(-1,7)
            b=np.fromfile(out/f'{name}-{edit}/data.bin',dtype=np.int32).reshape(-1,7)
            assert np.array_equal(a[:,5:],b[:,5:]),name+' dry changed'
            if edit==0 or int(name.split('-')[3])>=5:
                assert np.array_equal(a,b),name+' steady/THROW changed'
            assert (baseline/f'{name}-{edit}/engine-state.bin').read_bytes()==(out/f'{name}-{edit}/engine-state.bin').read_bytes(),name+' voice/phase/RNG changed'
    # Negative controls: no edit has exactly zero residual; a stepped reference compared to itself
    # has ratio1 and therefore cannot pass the raw-transition0.5 spectral gate.
    # Measured no-edit streams from both source variants must subtract to zero.
    zero_a=np.fromfile(baseline/'0-0-7-0-0/data.bin',dtype=np.int32).reshape(-1,7).astype(float)
    zero_b=np.fromfile(out/'0-0-7-0-0/data.bin',dtype=np.int32).reshape(-1,7).astype(float)
    zero_residual=zero_b-zero_a
    zero_spectrum=np.fft.rfft(zero_residual[8064:8320,0]*np.hanning(256))
    zero_hf=float(np.sqrt(np.sum(abs(zero_spectrum[47:])**2)))
    assert zero_hf==0 and np.array_equal(zero_a,zero_b)
    # Actual nonzero baseline step residual, divided by the identical measured reference.
    stepped_hf=old['0-0-7-0']['metrics'][0]['local_hf']
    assert stepped_hf>0
    stepped_ratio=stepped_hf/old['0-0-7-0']['metrics'][0]['local_hf']
    assert not stepped_ratio<=0.5
    (out/'comparison.json').write_text(json.dumps(dict(ratios=ratios,dry_steady_throw_engine_state_exact=True,
           negative_controls=dict(no_edit_stream='0-0-7-0-0/data.bin',no_edit_hf=zero_hf,stepped_baseline='0-0-7-0',stepped_reference_hf=stepped_hf,stepped_reference_ratio=stepped_ratio,stepped_reference_passes=False)),indent=2))
    for mode in range(9):
        for group in ('raw','master'):
            values=[v[k] for name,v in ratios.items() if name.endswith('-'+str(mode))
                    for k in (range(3) if group=='raw' else range(3,5))
                    if group=='master' or int(name.split('-')[2])&(1<<k)]
            print(mode,group,{q:float(np.median([v[q] for v in values])) for q in ['d1','d2','hf','local_hf']})
