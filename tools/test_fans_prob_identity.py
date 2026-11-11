#!/usr/bin/env python3
"""Verify that the fan add-on does not change existing segment probabilities.

Uses a copy of site/data/segment_risk*.json (latest run in the checkout).
Writes segment_fans*.json next to a temporary copy and diffs p/lead/em/tp/tm.
Also reports (but does not apply) what would change if p were overwritten
with the apex probability — Stage A keeps those values identical.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
import fans  # noqa: E402

REPO = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/workspace/fa_cron')


def hypothetic_overwrite(risk, rows):
    """What would happen if p[seg] were replaced by p[apex]. Not applied."""
    p = list(risk.get('p') or [])
    changes = []
    for r in rows:
        i = int(r['id'])
        a = r.get('fan_apex_seg')
        if a is None or i >= len(p) or int(a) >= len(p):
            continue
        if r.get('kind') == 'ext' or 'extension' in (r.get('layer') or ''):
            continue
        pv, pa = p[i], p[int(a)]
        if pv != pa:
            changes.append(dict(id=i, fan_id=r.get('fan_id'), p=pv, p_apex=pa, apex=int(a)))
    return changes


def main():
    site = REPO / 'site' / 'data'
    src_d = jload = json.loads
    d0 = src_d((site / 'segment_risk.json').read_text())
    n0 = src_d((site / 'segment_risk_nondesert.json').read_text())
    # snapshot before
    before_d = json.loads(json.dumps(d0))
    before_n = json.loads(json.dumps(n0))
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        shutil.copy2(site / 'segment_risk.json', td / 'segment_risk.json')
        shutil.copy2(site / 'segment_risk_nondesert.json', td / 'segment_risk_nondesert.json')
        fans.write_from_job(site_dir=td, root=REPO, issued=d0.get('issued'), t0=d0.get('t0'))
        after_d = json.loads((td / 'segment_risk.json').read_text())
        after_n = json.loads((td / 'segment_risk_nondesert.json').read_text())
        sf_d = json.loads((td / 'segment_fans.json').read_text())
        sf_n = json.loads((td / 'segment_fans_nondesert.json').read_text())
    ok_d, diff_d = fans.probabilities_unchanged(before_d, after_d)
    ok_n, diff_n = fans.probabilities_unchanged(before_n, after_n)
    # Synthetic: even if p[seg] and p[apex] differ, write_from_job must not touch them.
    synth = json.loads(json.dumps(before_d))
    if synth.get('p'):
        for i,v in enumerate(synth['p']):
            if v is not None:
                synth['p'][i] = round((i % 97) / 100.0, 3)
        with tempfile.TemporaryDirectory() as td2:
            td2 = Path(td2)
            (td2 / 'segment_risk.json').write_text(json.dumps(synth), encoding='utf-8')
            (td2 / 'segment_risk_nondesert.json').write_text(json.dumps(before_n), encoding='utf-8')
            fans.write_from_job(site_dir=td2, root=REPO, issued=synth.get('issued'), t0=synth.get('t0'))
            after_s = json.loads((td2 / 'segment_risk.json').read_text())
        ok_s, diff_s = fans.probabilities_unchanged(synth, after_s)
        if not ok_s:
            raise SystemExit('SYNTHETIC_IDENTITY_FAILED '+json.dumps(diff_s))
        synth_ok = True
    else:
        synth_ok = None
        diff_s = []
    # mapping
    desert, north, exts_d, exts_n = fans.load_mapping(REPO)
    hyp_d = hypothetic_overwrite(before_d, desert)
    hyp_n = hypothetic_overwrite(before_n, north)
    report = dict(
        ok=ok_d and ok_n,
        desert=dict(unchanged=ok_d, diffs=diff_d, n_flagged=sf_d.get('n_flagged'),
                    n_extensions=sf_d.get('n_extensions'),
                    hypothetic_p_overwrite_n=len(hyp_d), hypothetic_examples=hyp_d[:12]),
        nondesert=dict(unchanged=ok_n, diffs=diff_n, n_flagged=sf_n.get('n_flagged'),
                       n_extensions=sf_n.get('n_extensions'),
                       hypothetic_p_overwrite_n=len(hyp_n), hypothetic_examples=hyp_n[:12]),
        note='segment_risk*.json were not written by fans.py; p/lead/em/tp/tm stay identical. '
             'hypothetic_* shows how many model segments would change if Stage B/overwrite were applied.',
    )
    out = Path('/workspace/flood/staging/alluvial_fans/impl/out/prob_identity.json')
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report['ok']:
        sys.exit(2)
    print('IDENTITY_OK')


if __name__ == '__main__':
    main()
