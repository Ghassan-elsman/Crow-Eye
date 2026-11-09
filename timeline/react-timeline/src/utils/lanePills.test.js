// Every pill hides its own marks in the artifacts lane, not only its links.
// The lane consulted the Key times and Event Log pills alone, so switching
// Prefetch, LNK, BAM, AmCache, ShimCache, Recycle Bin or Registry off removed
// their links and left every mark drawn.
import { describe, expect, it } from 'vitest';
import { laneVisibleSources, pillOf } from './laneSources';

const DATA = {
  prefetch: [{ executable_name: 'a.exe' }],
  lnk: [{ Source_Name: 'b.lnk' }],
  bam: [{ program: 'c.exe' }],
  dam: [{ program: 'd.exe' }],
  shimcache: [{ path: 'e.exe' }],
  recyclebin: [{ original_filename: 'f.txt' }],
  amcache: { application_files: [{ name: 'g.exe' }] },
  imported: [{ name: 'h' }],
  event_logs: [{ EventID: 4688 }],
  registry: { UserAssist: [{ program_name: 'i.exe' }], key_times: [{ filename: 'k', bounded_time: 1 }] },
};
const ON = { prefetch: true, lnk: true, bam: true, shimcache: true, recyclebin: true,
             amcache: true, registry: true, event_logs: true, key_times: false };
const types = (active) => laneVisibleSources(DATA, active).filter(s => s.items).map(s => s.type).sort();

describe('the artifacts lane follows every pill', () => {
  it('draws each source while its pill is on', () => {
    expect(types(ON)).toEqual(['amcache', 'bam', 'dam', 'event_logs', 'imported', 'lnk',
                               'prefetch', 'recyclebin', 'shimcache', 'userassist']);
  });

  it('hides a source when its pill is off', () => {
    for (const pill of ['prefetch', 'lnk', 'bam', 'shimcache', 'recyclebin', 'amcache', 'registry']) {
      const got = types({ ...ON, [pill]: false });
      for (const t of got) expect(pillOf(t)).not.toBe(pill);
    }
    expect(types({ ...ON, bam: false })).not.toContain('dam');            // DAM rides with BAM
    expect(types({ ...ON, registry: false })).not.toContain('userassist');
  });

  it('keeps imported evidence, and the two opt-in pills start off', () => {
    const all = Object.fromEntries(Object.keys(ON).map(k => [k, false]));
    expect(types(all)).toEqual(['imported']);
    expect(types(ON)).not.toContain('key_times');
    expect(types({ ...ON, key_times: true })).toContain('key_times');
  });
});
