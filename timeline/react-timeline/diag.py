import sys, json
sys.path.insert(0, '.')
from timeline.timeline_bridge import TimelineBridge

b = TimelineBridge(r'C:\Users\Ghass\Downloads\test 1\Target_Artifacts')

# Phase 1: Time bounds
bounds = json.loads(b.getTimeBounds())
print('=== TIME BOUNDS ===')
print('  start:', bounds.get('start'))
print('  end:  ', bounds.get('end'))

# Phase 2: Aggregated counts  
agg = json.loads(b.getAggregatedCounts(bounds['start'], bounds['end']))
print('\n=== AGGREGATED COUNTS ===')
for source, rows in agg.items():
    if isinstance(rows, list) and len(rows) > 0:
        total_count = sum(r.get('count', 0) for r in rows)
        print(f'  {source}: {len(rows)} days, {total_count} total events')
        print(f'    first day: {rows[0]}')

# Phase 3: Detail data for one week
s = '2026-02-06T00:00:00.000Z'
e = '2026-02-13T23:59:59.000Z'
print(f'\n=== DETAIL DATA for {s} to {e} ===')

for method in ['getSessionData', 'getSrumAppData', 'getSrumNetData', 'getMftUsnData',
               'getPrefetchData', 'getLnkData', 'getBamData', 'getRegistryData',
               'getAmcacheData', 'getShimcacheData', 'getRecyclebinData']:
    try:
        raw = getattr(b, method)(s, e)
        data = json.loads(raw)
        if isinstance(data, list):
            print(f'  {method}: {len(data)} items ({len(raw)} bytes)')
        elif isinstance(data, dict):
            counts = {}
            for k, v in data.items():
                if isinstance(v, list):
                    counts[k] = len(v)
                else:
                    counts[k] = type(v).__name__
            print(f'  {method}: {counts} ({len(raw)} bytes)')
    except Exception as ex:
        print(f'  {method}: ERROR - {ex}')

print('\nDone.')
