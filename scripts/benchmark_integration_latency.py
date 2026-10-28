"""Alternating repeated end-to-end timing of frozen and current engines, same inputs/exports."""
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time


def benchmark(before, after, dataset, repeat):
    rows=[]
    for i in range(repeat):
        for label, engine in ([('before',before),('after',after)] if i%2==0 else [('after',after),('before',before)]):
            with tempfile.TemporaryDirectory(prefix='knitcode-timing-') as tmp:
                start=time.perf_counter()
                result=subprocess.run([sys.executable,str(engine/'pycg_benchmark.py'),
                    '--benchmark',str(dataset),'--output',tmp,'--analysis-profile','integrated',
                    '--call-policy','supported'],cwd=engine,capture_output=True,text=True,timeout=180)
                elapsed=time.perf_counter()-start
                if result.returncode:
                    raise RuntimeError(result.stderr[-3000:])
                summary=json.loads((Path(tmp)/'summary.json').read_text())
                rows.append(dict(iteration=i+1,version=label,wall_seconds=elapsed,
                                 projects={r['project']:r['seconds'] for r in summary}))
    medians={name:statistics.median(r['wall_seconds'] for r in rows if r['version']==name)
             for name in ('before','after')}
    return dict(repeat=repeat,scope='Same 5 projects, includes process startup, selected engine pipeline and all JSON/HTML exports',
                rows=rows,median_seconds=medians,
                relative_change=(medians['after']/medians['before']-1))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before',type=Path,required=True);parser.add_argument('--after',type=Path,default=Path('.'))
    parser.add_argument('--benchmark',type=Path,required=True);parser.add_argument('--repeat',type=int,default=3)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.repeat<1:parser.error('--repeat must be positive')
    result=benchmark(args.before.resolve(),args.after.resolve(),args.benchmark.resolve(),args.repeat)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
