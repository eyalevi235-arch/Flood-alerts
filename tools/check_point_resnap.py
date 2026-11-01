"""Engine side of the v3b re-snap. Desert custom points keep their stored segment."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'engine'))
import run_job as job  # noqa: E402


def fail(msg):
    print('FAIL', msg)
    sys.exit(1)


def check(cond, msg):
    if not cond:
        fail(msg)
    print('ok', msg)


check(job.resolve_north_segment(32.74792, 35.07458, 0) == 1, 'engine maps v2 seg 0 to v3b seg 1')
check(job.resolve_north_segment(32.49958, 34.98375, 2) == 3, 'engine maps v2 seg 2 to v3b seg 3')
check(job.resolve_north_segment(32.63458, 35.15042, 85) is None, 'unmapped v2 seg 85 is outside 60 m')
check(job.resolve_north_segment(32.19125, 35.36542, 195) is None, 'unmapped v2 seg 195 is outside 60 m')
check(job.north_id_map().get('85') is None and job.north_id_map().get('195') is None, 'those ids are missing from the map')

sub = {
    'uid': 'uabcdefg',
    'threshold': 0.3,
    'push': {
        'endpoint': 'https://fcm.googleapis.com/fcm/send/abc',
        'keys': {'p256dh': 'A' * 88, 'auth': 'B' * 22},
    },
    'custom': [
        {'id': 'Mnorth001', 'region': 'north_center', 'seg': 0, 'sid': '900079', 'lat': 32.74792, 'lon': 35.07458},
        {'id': 'Mnorth085', 'region': 'north_center', 'seg': 85, 'sid': '8145', 'lat': 32.63458, 'lon': 35.15042},
        {'id': 'Mdesert01', 'seg': 12, 'sid': '55170', 'lat': 30.95, 'lon': 35.08},
    ],
}
cleaned = job.clean_sub(sub)
by_id = {c['id']: c for c in cleaned['custom']}
check(by_id['Mnorth001']['seg'] == 1 and by_id['Mnorth001']['region'] == 'north_center', 'subscription north point is rewritten to seg 1')
check('Mnorth085' not in by_id, 'unmapped north point outside the radius is not sent onward')
check(by_id['Mdesert01']['seg'] == 12 and 'region' not in by_id['Mdesert01'], 'desert point keeps seg 12')
check(job.resolve_desert_segment(30.95, 35.08, 12) == 12, 'desert seg 12 still exists and is kept')
r106 = job.resolve_desert_segment(30.61208, 35.51292, 106)
check(r106 != 106, 'removed desert seg 106 is not kept (got %s)' % r106)
check(job.resolve_desert_segment(30.0, 36.5, 106) is None, 'removed desert seg far from any channel is dropped')
check(len(job.desert_segments()) == 9839, 'desert segment count is 9839')
print('engine resnap checks passed')
