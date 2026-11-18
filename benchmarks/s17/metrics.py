"""Independent Q1 summaries; arithmetic never makes development data a gate."""
import math
import random


def wilson(success,total):
    if not total:return None
    z=1.959963984540054;p=success/total;den=1+z*z/total
    center=(p+z*z/(2*total))/den;radius=z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/den
    return [max(0,center-radius),min(1,center+radius)]


def aggregate(rows):
    eligible=[r for r in rows if r['eligible']]
    tp,fp,fn=(sum(r.get(k,0) for r in eligible) for k in ('tp','fp','fn'))
    return {'tp':tp,'fp':fp,'fn':fn,'precision':tp/(tp+fp) if tp+fp else None,'recall':tp/(tp+fn) if tp+fn else None,
        'precision_wilson95':wilson(tp,tp+fp),'recall_wilson95':wilson(tp,tp+fn),
        'eligible_cases':len(eligible),'unlabelled_cases':len(rows)-len(eligible),
        'unlabelled_case_share':1-len(eligible)/len(rows) if rows else None,
        'unlabelled_predictions':sum(r.get('unlabelled_predictions',0) for r in rows),
        'detector_errors':sum(r.get('detector_error',False) for r in rows),
        'sample_status':'sufficient counts' if tp+fp>=20 and tp+fn>=20 else 'insufficient data',
        'gate_status':'development only; no acceptance verdict'}


def clustered(rows):
    repos=sorted({r['repository'] for r in rows if r['eligible']})
    if len(repos)<5:return {'status':'not estimable','repositories':len(repos),'precision':None,'recall':None}
    grouped={repo:[r for r in rows if r['repository']==repo] for repo in repos};rng=random.Random(9042026);values={'precision':[],'recall':[]}
    for _ in range(2000):
        stats=aggregate([r for repo in rng.choices(repos,k=len(repos)) for r in grouped[repo]])
        for key in values:
            if stats[key] is not None:values[key].append(stats[key])
    return {'repositories':len(repos),'replicates':2000,'seed':9042026,
            **{k:[sorted(v)[int(.025*(len(v)-1))],sorted(v)[int(.975*(len(v)-1))]] if v else None for k,v in values.items()}}
