import test from 'node:test';
import assert from 'node:assert/strict';
import {SHOT_STATES, shotState, shotStateOf, newTakeCount, newTakeCountOf, isAdopted, adoptedCount, mergeTakes, nextNewTake, thumbOf, filmNeighbors, filmSegments, filmSummary, playlist,
  adoptionBody, proposalTakeUrls, takeOnlyProposal} from '../src/takeModel.js';
import {rowProposals} from '../src/proposalModel.js';

const at = minutes => new Date(Date.UTC(2026, 9, 27, 10, minutes)).toISOString();
const take = (n, extra = {}) => ({videoId: 'vd_' + n, url: `/take/${n}.mp4`, selected: false, createdAt: at(n), ...extra});
const adoption = (n, minutes = n) => ({adopted: true, url: `/take/${n}.mp4`, at: at(minutes), by: 'u1'});
const shot = (n, extra = {}) => ({shotId: 'sh_demo_b' + n, rowId: 'b' + n, shotIndex: 'S0' + n, reviewStatus: 'Queued', selectedVideoUrl: null, selectedImageUrl: null, previsVideoUrl: null, trim: {in: 0, out: null}, adoption: null, ...extra});
const adopted = (n, extra = {}) => shot(n, {reviewStatus: 'Approved', selectedVideoUrl: `/take/${n}.mp4`, selectedImageUrl: `/still/${n}.png`, adoption: adoption(n), ...extra});

test('state priority runs blocked, generating, new take, retake, adopted, empty', () => {
  const takes = [take(1), take(5)], record = adoption(1, 2);
  assert.equal(shotState({status: 'Blocked', adoption: record, takes, inFlight: true}), 'blocked', 'blocked beats everything');
  assert.equal(shotState({status: 'Approved', adoption: record, takes, inFlight: true}), 'generating', 'a running task beats a new take');
  assert.equal(shotState({status: 'Retake', adoption: record, takes, inFlight: false}), 'new_take', 'a new take beats retake');
  assert.equal(shotState({status: 'Approved', adoption: record, takes, inFlight: false}), 'new_take', 'a new take beats adopted');
  assert.equal(shotState({status: 'Retake', adoption: record, takes: [take(1)]}), 'retake');
  assert.equal(shotState({status: 'Approved', adoption: record, takes: [take(1)]}), 'adopted');
  assert.equal(shotState({status: 'Queued', takes: []}), 'empty');
  assert.equal(shotState({status: '', takes: []}), 'empty');
  assert.equal(shotState({status: 'Blocked', takes: []}), 'blocked');
  assert.equal(shotState({status: 'Retake', takes: [], inFlight: true}), 'generating');
  assert.deepEqual(SHOT_STATES, ['blocked', 'generating', 'new_take', 'retake', 'adopted', 'empty']);
});

test('legacy Chinese statuses read like their English values', () => {
  assert.equal(shotState({status: '卡住', takes: [take(1)]}), 'blocked');
  assert.equal(shotState({status: '重抽', takes: []}), 'retake');
  assert.equal(shotState({status: '已完成', adoption: adoption(1), takes: [take(1)]}), 'adopted');
  assert.equal(shotState({status: '等待審核', takes: [take(1)]}), 'new_take', 'a Pending Review shot with a take is a new take');
  assert.equal(shotState({status: '等待回覆', takes: [take(1)]}), 'new_take');
  assert.equal(shotState({status: '未開始', takes: []}), 'empty');
});

test('a take is new when it is later than the adoption', () => {
  const record = adoption(1, 5);
  assert.equal(shotState({status: 'Approved', adoption: record, takes: [take(1), take(4)]}), 'adopted', 'older takes are not new');
  assert.equal(shotState({status: 'Approved', adoption: record, takes: [take(1), take(6)]}), 'new_take');
  assert.equal(shotState({status: 'Approved', adoption: record, takes: [take(1), take(5)]}), 'adopted', 'the same minute is not later');
  assert.equal(shotState({status: 'Approved', adoption: record, takes: [take(1, {createdAt: undefined}), take(7, {createdAt: null})]}), 'adopted', 'takes without a time are older');
  assert.equal(shotState({status: 'Approved', adoption: record, takes: [take(1), take(7)]}), 'new_take');
  assert.equal(newTakeCount({status: 'Approved', adoption: record, takes: [take(6), take(7), take(2)]}), 2);
  assert.equal(newTakeCount({status: 'Approved', adoption: record, takes: [take(1, {createdAt: at(9)})]}), 0, 'the adopted take itself is never new');
});

test('nothing adopted: any take is a new take, no take is empty', () => {
  for (const status of ['Queued', 'In Progress', 'Pending Review', '', 'Rendering Video']) {
    assert.equal(shotState({status, takes: [take(1)]}), 'new_take', status);
    assert.equal(shotState({status, takes: []}), 'empty', status);
  }
  assert.equal(newTakeCount({status: 'Queued', takes: [take(1), take(2), take(3, {createdAt: undefined})]}), 3);
  assert.equal(shotState({status: 'Queued'}), 'empty', 'no takes loaded at all');
});

test('old data: untimed candidates are older than the adoption', () => {
  const legacy = [{videoId: 'vd_a', url: '/a.mp4', selected: false}, {videoId: 'vd_b', url: '/b.mp4', selected: true}];
  assert.equal(shotState({status: 'Approved', adoption: adoption(2, 5), takes: legacy}), 'adopted');
  assert.equal(newTakeCount({status: 'Approved', adoption: adoption(2, 5), takes: legacy}), 0);
});

test('old data: an Approved shot with no adoption record is adopted with the take in the cell', () => {
  const legacy = [{videoId: 'vd_a', url: '/a.mp4', selected: false}, {videoId: 'vd_b', url: '/b.mp4', selected: true}];
  assert.equal(shotState({status: 'Approved', adoption: null, takes: legacy}), 'adopted', 'untimed candidates, no record');
  assert.equal(shotState({status: 'Approved', takes: legacy}), 'adopted');
  assert.equal(shotState({status: 'Approved', adoption: null, takes: []}), 'adopted');
  assert.equal(shotState({status: '已完成', adoption: null, takes: legacy}), 'adopted');
  // The cell's take is untimed (adopted before times existed): a take with a time can only have come after it.
  assert.equal(shotState({status: 'Approved', adoption: null, takes: [...legacy, take(3)]}), 'new_take');
  // The cell's take has a time: only a later take is new, an earlier timed one is not.
  const cell = take(5, {selected: true});
  assert.equal(shotState({status: 'Approved', adoption: null, takes: [take(2), cell]}), 'adopted');
  assert.equal(shotState({status: 'Approved', adoption: null, takes: [take(2), cell, take(8)]}), 'new_take');
  assert.equal(newTakeCount({status: 'Approved', adoption: null, takes: [take(2), cell, take(8), take(9)]}), 2);
});

test('retake: a shot being re-shot after an adoption is retake until a take newer than the adoption arrives', () => {
  const record = adoption(1, 3);
  assert.equal(shotState({status: 'Retake', adoption: record, takes: [take(1), take(2)]}), 'retake', 'the old takes are not new');
  assert.equal(shotState({status: 'Retake', adoption: record, takes: [take(1), take(2), take(4)]}), 'new_take');
  assert.equal(shotState({status: 'Retake', adoption: record, takes: [take(1)], inFlight: true}), 'generating');
  assert.equal(shotState({status: 'Retake', adoption: null, takes: []}), 'retake', 'nothing to compare and no takes');
  assert.equal(shotState({status: 'Retake', adoption: null, takes: [take(1)]}), 'new_take', 'never adopted: a take is a take');
});

test('a shot view without loaded takes is read through its summary, then through its cell', () => {
  const summary = (total, newSinceAdoption) => ({total, newSinceAdoption});
  assert.equal(shotStateOf(adopted(1, {takeSummary: summary(2, 0)})), 'adopted');
  assert.equal(shotStateOf(adopted(1, {takeSummary: summary(3, 2)})), 'new_take');
  assert.equal(newTakeCountOf(adopted(1, {takeSummary: summary(3, 2)})), 2);
  assert.equal(shotStateOf(shot(2, {reviewStatus: 'Pending Review', takeSummary: summary(2, 0)})), 'new_take', 'unadopted: the total counts');
  assert.equal(newTakeCountOf(shot(2, {takeSummary: summary(2, 0)})), 2);
  assert.equal(shotStateOf(shot(3, {takeSummary: summary(0, 0)})), 'empty');
  // No summary (an older server): the video in the cell is the one take.
  assert.equal(shotStateOf(shot(4, {reviewStatus: 'Pending Review', selectedVideoUrl: '/take/4.mp4'})), 'new_take');
  assert.equal(shotStateOf(shot(5, {reviewStatus: 'Approved', selectedVideoUrl: '/take/5.mp4'})), 'adopted');
  assert.equal(shotStateOf(shot(6)), 'empty');
  assert.equal(shotStateOf(shot(7, {reviewStatus: 'Blocked', selectedVideoUrl: '/take/7.mp4'})), 'blocked');
  assert.equal(shotStateOf(adopted(8), {inFlight: true}), 'generating', 'extra facts from the page');
  assert.equal(shotStateOf({...adopted(9), inFlight: true}), 'generating', 'a decorated shot');
  assert.equal(shotStateOf(adopted(1, {takeSummary: summary(3, 2)}), {takes: [take(1)]}), 'adopted', 'loaded takes win over the summary');
  assert.equal(shotStateOf(adopted(1, {takes: [take(1), take(4)]})), 'new_take', 'a decorated shot carries its takes');
});

const view = (n, extra) => ({url: `/take/${n}.mp4`, ...extra});
const mediaProposal = (id, rid, changes, extra = {}) => ({id, action: 'table_edit', status: 'pending', created_at: at(id), target: {tab_key: 'cinema-studio'},
  review: {groups: [{index: 0, row_id: rid, row_number: 1, label: 'Row 1', changes}], partial_allowed: true, version: 'v' + id}, ...extra});

test('merged takes: one list, newest first, one entry per url, each with its source', () => {
  const candidates = [take(1), take(3, {selected: true}), take(2)];
  const proposals = rowProposals([mediaProposal(4, 'b1', [{column: 'Cinema Shot', before: '', after: '[Video](/take/4.mp4)'}])], 'b1', 'cinema-studio');
  const merged = mergeTakes(candidates, proposals, {status: 'Queued'});
  assert.deepEqual(merged.map(item => [item.url, item.source, item.number]), [['/take/4.mp4', 'proposal', 4], ['/take/3.mp4', 'candidate', 3], ['/take/2.mp4', 'candidate', 2], ['/take/1.mp4', 'candidate', 1]]);
  const [proposed, chosen] = merged;
  assert.equal(proposed.proposalId, 4);assert.equal(proposed.videoId, null);assert.equal(proposed.entry, proposals[0]);assert.equal(proposed.createdAt, at(4));
  assert.equal(chosen.videoId, 'vd_3');assert.equal(chosen.proposalId, null);assert.equal(chosen.selected, true);assert.equal(chosen.candidate, candidates[1]);
  assert.equal(typeof chosen.time, 'number');
});

test('merged takes: a url that is both a candidate and a proposal is one take, and the candidate is the one you adopt', () => {
  const proposals = rowProposals([mediaProposal(9, 'b1', [{column: 'Cinema Shot', before: '', after: '[Video](/take/2.mp4)'}])], 'b1');
  const merged = mergeTakes([take(1), take(2)], proposals);
  assert.deepEqual(merged.map(item => [item.url, item.source]), [['/take/2.mp4', 'candidate'], ['/take/1.mp4', 'candidate']]);
  assert.equal(merged[0].videoId, 'vd_2');
  assert.equal(merged[0].entry, proposals[0], 'still reachable as a proposal');
  assert.equal(mergeTakes([take(1), take(1, {videoId: 'vd_dup'})], []).length, 1, 'duplicate candidates collapse too');
});

test('merged takes: only video changes of a proposal are takes', () => {
  const asset = letter => '/projects/api/demo/assets/pa_' + letter.repeat(32);
  const proposals = rowProposals([mediaProposal(5, 'b1', [
    {column: 'Keyframe', before: '', after: '![](/frame/5.png)'},
    {column: 'Keyframe', before: '', after: `![Image](${asset('c')})`},
    {column: 'Prompt', before: 'a', after: 'b'},
    {column: 'Cinema Shot', before: '', after: '[Video](/take/5.mp4)'},
    {column: 'Remastered Video', before: '', after: `[Video](${asset('a')})`},
    {column: 'Output', before: '', after: asset('d')},
    {column: 'Alt', before: '', after: '[video](https://example.org/alt.mp4)'},
    {column: 'Alt 2', before: '', after: 'https://example.org/bare.webm'},
    {column: 'Notes', before: '', after: asset('b')},
    {column: 'Link', before: '', after: 'see https://example.org/page'},
    {column: 'Status', before: 'Queued', after: 'Pending Review'}])], 'b1');
  assert.deepEqual(mergeTakes([], proposals).map(item => item.url).sort(),
    ['/take/5.mp4', asset('a'), asset('d'), 'https://example.org/alt.mp4', 'https://example.org/bare.webm'].sort(), 'videos only: not the frames, the notes asset, or plain text');
  assert.deepEqual(mergeTakes([], rowProposals([], 'b1')), []);
  assert.deepEqual(mergeTakes(undefined, undefined), []);
  assert.deepEqual(mergeTakes([], [{url: '/take/7.mp4', proposalId: 7}]).map(item => [item.url, item.proposalId]), [['/take/7.mp4', 7]], 'a plain {url} entry');
});

test('merged takes: untimed takes sort after timed ones, later input first', () => {
  const merged = mergeTakes([{videoId: 'vd_a', url: '/a.mp4'}, take(2), {videoId: 'vd_b', url: '/b.mp4'}, take(1)], []);
  assert.deepEqual(merged.map(item => item.url), ['/take/2.mp4', '/take/1.mp4', '/b.mp4', '/a.mp4']);
  assert.equal(merged[2].time, null);
  assert.deepEqual(merged.map(item => item.number), [4, 3, 2, 1]);
  const same = mergeTakes([take(1), take(1, {url: '/other.mp4', createdAt: at(1)})], []);
  assert.deepEqual(same.map(item => item.url), ['/other.mp4', '/take/1.mp4'], 'equal times: the later input is newer');
});

test('merged takes: the adopted take is marked, and new takes are those after the adoption', () => {
  const candidates = [take(1), take(2, {selected: true}), take(6)];
  const merged = mergeTakes(candidates, [], {status: 'Approved', adoption: adoption(2, 3)});
  assert.deepEqual(merged.map(item => [item.number, item.adopted, item.isNew]), [[3, false, true], [2, true, false], [1, false, false]]);
  assert.equal(shotState({status: 'Approved', adoption: adoption(2, 3), takes: merged}), 'new_take', 'merged takes feed shotState');
  const retaking = mergeTakes(candidates, [], {status: 'Retake', adoption: adoption(2, 3)});
  assert.deepEqual(retaking.map(item => item.adopted), [false, false, false], 'a shot being re-shot has nothing in the cut');
  assert.deepEqual(retaking.map(item => item.isNew), [true, false, false]);
  const unadopted = mergeTakes(candidates, [], {status: 'Pending Review'});
  assert.deepEqual(unadopted.map(item => [item.adopted, item.isNew]), [[false, true], [false, true], [false, true]]);
  // Old data: no record, the take in the cell is the adopted one.
  const legacy = mergeTakes([{videoId: 'vd_a', url: '/a.mp4'}, {videoId: 'vd_b', url: '/b.mp4', selected: true}], [], {status: 'Approved', adoption: null});
  assert.deepEqual(legacy.map(item => [item.url, item.adopted, item.isNew]), [['/b.mp4', true, false], ['/a.mp4', false, false]]);
  assert.deepEqual(mergeTakes([take(1)], [], {}).map(item => [item.adopted, item.isNew]), [[false, true]], 'no shot facts: nothing adopted');
});

test('a pending proposal newer than the adoption is a new take; an older one is not', () => {
  const entries = id => rowProposals([mediaProposal(id, 'b1', [{column: 'Cinema Shot', before: '', after: `[Video](/take/${id}.mp4)`}])], 'b1');
  const options = {status: 'Approved', adoption: adoption(2, 5)};
  assert.deepEqual(mergeTakes([take(2, {selected: true})], entries(9), options).map(item => [item.source, item.isNew]), [['proposal', true], ['candidate', false]]);
  assert.deepEqual(mergeTakes([take(2, {selected: true})], entries(4), options).map(item => [item.source, item.isNew]), [['proposal', false], ['candidate', false]], 'a proposal from before the adoption');
  assert.equal(shotState({status: 'Approved', adoption: options.adoption, takes: mergeTakes([take(2, {selected: true})], entries(9), options)}), 'new_take');
  assert.equal(shotState({status: 'Approved', adoption: options.adoption, takes: mergeTakes([take(2, {selected: true})], entries(4), options)}), 'adopted');
});

test('the next new take: forward from the current shot, wrapping from the end to the start', () => {
  const shots = [adopted(1, {takeSummary: {total: 1, newSinceAdoption: 0}}), shot(2, {reviewStatus: 'Pending Review', selectedVideoUrl: '/take/2.mp4'}),
    adopted(3), shot(4, {reviewStatus: 'Pending Review', selectedVideoUrl: '/take/4.mp4'}), adopted(5)];
  assert.equal(nextNewTake(shots, shots[0].shotId), shots[1]);
  assert.equal(nextNewTake(shots, shots[1].shotId), shots[3], 'skips the current shot and shots without a new take');
  assert.equal(nextNewTake(shots, shots[3].shotId), shots[1], 'wraps from the end to the start');
  assert.equal(nextNewTake(shots, shots[4].shotId), shots[1], 'from the last shot it wraps at once');
  assert.equal(nextNewTake(shots, shots[2].shotId), shots[3]);
  assert.equal(nextNewTake(shots, null), shots[1], 'no current shot: from the first');
  assert.equal(nextNewTake(shots, 'sh_nope'), shots[1], 'a shot that is not in the list: from the first');
});

test('after an adoption the shot stops waiting and the next shot with a new take is the one to jump to', () => {
  const waiting = id => shot(id, {reviewStatus: 'Pending Review', selectedVideoUrl: `/take/${id}.mp4`});
  let shots = [waiting(1), waiting(2), adopted(3)];
  assert.equal(adoptedCount(shots), 1);
  assert.equal(shotStateOf(shots[0]), 'new_take');
  shots = [adopted(1), shots[1], shots[2]];
  assert.equal(shotStateOf(shots[0]), 'adopted');
  assert.equal(adoptedCount(shots), 2);
  assert.equal(nextNewTake(shots, shots[0].shotId), shots[1]);
  shots = [shots[0], adopted(2), shots[2]];
  assert.equal(nextNewTake(shots, shots[1].shotId), null, 'nothing left to pick: stay on the shot');
  assert.equal(adoptedCount(shots), 3);
});

test('the next new take is null when no other shot has one', () => {
  const quiet = [adopted(1), adopted(2), shot(3)];
  assert.equal(nextNewTake(quiet, quiet[0].shotId), null);
  assert.equal(nextNewTake([], 'sh_demo_b1'), null);
  const only = [adopted(1), shot(2, {reviewStatus: 'Pending Review', selectedVideoUrl: '/take/2.mp4'}), adopted(3)];
  assert.equal(nextNewTake(only, only[1].shotId), null, 'the current shot itself does not count');
  assert.equal(nextNewTake(only, only[0].shotId), only[1]);
  const busy = [adopted(1), shot(2, {reviewStatus: 'Pending Review', selectedVideoUrl: '/take/2.mp4', inFlight: true}), shot(3, {reviewStatus: 'Blocked', selectedVideoUrl: '/take/3.mp4'})];
  assert.equal(nextNewTake(busy, busy[0].shotId), null, 'generating and blocked shots are not waiting for a pick');
});

test('film neighbours: the previous, this and next shot with a thumbnail from the adopted take, the newest take, the previs, or nothing', () => {
  const shots = [adopted(1), shot(2, {reviewStatus: 'Pending Review', selectedVideoUrl: '/take/2.mp4', selectedImageUrl: '/still/2.png', previsVideoUrl: '/previs/2.mp4'}),
    shot(3, {previsVideoUrl: '/previs/3.mp4'}), shot(4)];
  const middle = filmNeighbors(shots, shots[1].shotId);
  assert.equal(middle.index, 1);assert.equal(middle.total, 4);
  assert.deepEqual([middle.prev.shotIndex, middle.current.shotIndex, middle.next.shotIndex], ['S01', 'S02', 'S03']);
  assert.deepEqual(middle.prev.thumb, {kind: 'adopted', videoUrl: '/take/1.mp4', posterUrl: '/still/1.png'});
  assert.deepEqual(middle.current.thumb, {kind: 'latest', videoUrl: '/take/2.mp4', posterUrl: '/still/2.png'});
  assert.deepEqual(middle.next.thumb, {kind: 'previs', videoUrl: '/previs/3.mp4', posterUrl: null});
  assert.deepEqual(thumbOf(shots[3]), {kind: 'none', videoUrl: null, posterUrl: null});
  assert.deepEqual([middle.prev.state, middle.current.state, middle.next.state], ['adopted', 'new_take', 'empty']);
  assert.deepEqual([middle.prev.adopted, middle.current.adopted], [true, false]);
  const first = filmNeighbors(shots, shots[0].shotId), last = filmNeighbors(shots, shots[3].shotId);
  assert.equal(first.prev, null);assert.equal(first.current.shotId, shots[0].shotId);assert.equal(first.next.shotIndex, 'S02');
  assert.equal(last.next, null);assert.equal(last.prev.shotIndex, 'S03');
  assert.deepEqual(filmNeighbors(shots, 'sh_nope'), {index: -1, total: 4, prev: null, current: null, next: null});
  assert.deepEqual(filmNeighbors([], 'x'), {index: -1, total: 0, prev: null, current: null, next: null});
});

test('the newest take stands in for an unadopted shot, and the adopted take beats a newer one', () => {
  const withTakes = shot(1, {reviewStatus: 'Pending Review', selectedVideoUrl: '/take/1.mp4', takes: [{url: '/take/3.mp4'}, {url: '/take/2.mp4'}, {url: '/take/1.mp4'}]});
  assert.deepEqual(thumbOf(withTakes), {kind: 'latest', videoUrl: '/take/3.mp4', posterUrl: null});
  assert.equal(thumbOf(adopted(1, {takes: [{url: '/take/9.mp4'}]})).videoUrl, '/take/1.mp4');
  assert.equal(thumbOf(adopted(1, {selectedVideoUrl: null, previsVideoUrl: '/previs/1.mp4'})).kind, 'previs', 'Approved with nothing in the cell is not in the cut');
});

test('film segments: width is the trimmed length for an adopted shot and the planned length for the rest', () => {
  const shots = [adopted(1, {trim: {in: 0.5, out: 3.5}}), shot(2, {reviewStatus: 'Pending Review', selectedVideoUrl: '/take/2.mp4', previsPlan: {seconds: 6}}),
    adopted(3), adopted(4, {previsPlan: {seconds: 8}}), shot(5)];
  const segments = filmSegments(shots, {measured: {'/take/3.mp4': 5}});
  assert.deepEqual(segments.map(segment => [segment.shotIndex, segment.seconds, segment.adopted, segment.planned, segment.trimmed]),
    [['S01', 3, true, false, true], ['S02', 6, false, true, false], ['S03', 5, true, false, false], ['S04', 8, true, false, false], ['S05', 4, false, true, false]],
    'trimmed 0.5-3.5, planned 6, measured 5, an unmeasured take falls back to its plan, default 4');
  assert.deepEqual(segments.map(segment => [segment.start, segment.end]), [[0, 3], [3, 9], [9, 14], [14, 22], [22, 26]]);
  assert.ok(Math.abs(segments.reduce((sum, segment) => sum + segment.share, 0) - 1) < 1e-9);
  assert.equal(segments[3].share, 8 / 26);
  assert.deepEqual(segments.map(segment => segment.state), ['adopted', 'new_take', 'adopted', 'adopted', 'empty']);
  assert.deepEqual(segments.map(segment => segment.index), [0, 1, 2, 3, 4]);
  assert.equal(segments[0].shotId, shots[0].shotId);
  assert.deepEqual(filmSegments([]), []);
});

test('film segments: a new take on an adopted shot leaves the cut as it was, and the state shows it', () => {
  const [segment] = filmSegments([adopted(1, {trim: {in: 1, out: 3}, takeSummary: {total: 3, newSinceAdoption: 2}})]);
  assert.deepEqual([segment.state, segment.seconds, segment.adopted], ['new_take', 2, true]);
  const [retaking] = filmSegments([adopted(1, {reviewStatus: 'Retake', previsPlan: {seconds: 6}})]);
  assert.deepEqual([retaking.state, retaking.seconds, retaking.adopted], ['retake', 6, false], 'a shot being re-shot is not in the cut: its plan');
});

test('film summary: how many shots are in the cut, how many have a take but are not, and how long it runs', () => {
  const shots = [adopted(1), shot(2, {reviewStatus: 'Pending Review', selectedVideoUrl: '/take/2.mp4'}), shot(3), adopted(4, {trim: {in: 0, out: 2}}), shot(5, {takeSummary: {total: 2, newSinceAdoption: 0}})];
  assert.deepEqual(filmSummary(shots), {shots: 5, adopted: 2, withTake: 2, seconds: 4 + 4 + 4 + 2 + 4});
  assert.deepEqual(filmSummary([]), {shots: 0, adopted: 0, withTake: 0, seconds: 0});
});

test('the playlist plays the adopted take trimmed, and fills the other shots by the chosen fill', () => {
  const shots = [adopted(1, {trim: {in: 0.5, out: 3.5}}), shot(2, {reviewStatus: 'Pending Review', selectedVideoUrl: '/take/2.mp4', previsVideoUrl: '/previs/2.mp4'}),
    shot(3, {previsVideoUrl: '/previs/3.mp4'}), shot(4), adopted(5)];
  const brief = list => list.map(item => [item.shotIndex, item.url, item.in, item.out, item.source]);
  assert.deepEqual(brief(playlist(shots, {fill: 'latest'})), [['S01', '/take/1.mp4', 0.5, 3.5, 'adopted'], ['S02', '/take/2.mp4', 0, null, 'latest'], ['S05', '/take/5.mp4', 0, null, 'adopted']],
    'latest: the newest take; a shot with no take is left out even if it has a previs');
  assert.deepEqual(brief(playlist(shots, {fill: 'previs'})), [['S01', '/take/1.mp4', 0.5, 3.5, 'adopted'], ['S02', '/previs/2.mp4', 0, null, 'previs'], ['S03', '/previs/3.mp4', 0, null, 'previs'], ['S05', '/take/5.mp4', 0, null, 'adopted']],
    'previs: an unadopted shot plays its previs even when it has a take');
  assert.deepEqual(brief(playlist(shots, {fill: 'skip'})), [['S01', '/take/1.mp4', 0.5, 3.5, 'adopted'], ['S05', '/take/5.mp4', 0, null, 'adopted']], 'skip: only what is in the cut');
  assert.deepEqual(playlist(shots), playlist(shots, {fill: 'latest'}), 'latest is the default');
  assert.deepEqual(playlist(shots, {fill: 'nonsense'}), playlist(shots, {fill: 'latest'}));
  assert.deepEqual(playlist(shots, {fill: 'skip'})[0], {shotId: shots[0].shotId, shotIndex: 'S01', index: 0, url: '/take/1.mp4', in: 0.5, out: 3.5, source: 'adopted'});
  assert.deepEqual(playlist([], {fill: 'latest'}), []);
});

test('the playlist fills with the newest merged take when the shot carries its takes, and plays an untrimmed or odd trim whole', () => {
  const shots = [shot(1, {reviewStatus: 'Retake', selectedVideoUrl: '/take/1.mp4', takes: [{url: '/take/4.mp4'}, {url: '/take/1.mp4'}]}),
    adopted(2, {trim: {in: 0, out: null}}), adopted(3, {trim: {in: 2, out: 1}}), adopted(4, {trim: {in: -1, out: 3}}), adopted(5, {trim: undefined})];
  assert.deepEqual(playlist(shots).map(item => [item.url, item.in, item.out, item.source]),
    [['/take/4.mp4', 0, null, 'latest'], ['/take/2.mp4', 0, null, 'adopted'], ['/take/3.mp4', 2, null, 'adopted'], ['/take/4.mp4', 0, 3, 'adopted'], ['/take/5.mp4', 0, null, 'adopted']]);
});

test('a trial take replaces only that shot in the playlist and changes nothing else', () => {
  const shots = [adopted(1, {trim: {in: 0.5, out: 3.5}}), adopted(2, {trim: {in: 0, out: 2}}), shot(3, {previsVideoUrl: '/previs/3.mp4'}), shot(4)];
  Object.freeze(shots);shots.forEach(item => Object.freeze(item));
  const trial = {shotId: shots[1].shotId, url: '/take/2b.mp4'}, counts = adoptedCount(shots);
  const tried = playlist(shots, {fill: 'skip', trial}), plain = playlist(shots, {fill: 'skip'});
  assert.deepEqual(tried.map(item => [item.shotIndex, item.url, item.in, item.out, item.source]), [['S01', '/take/1.mp4', 0.5, 3.5, 'adopted'], ['S02', '/take/2b.mp4', 0, null, 'trial']]);
  assert.deepEqual(tried[0], plain[0], 'the other items are the same');
  assert.deepEqual(plain.map(item => item.shotId), [shots[0].shotId, shots[1].shotId]);
  assert.equal(adoptedCount(shots), counts, 'a trial does not change how many shots are adopted');
  assert.equal(adoptedCount(shots), 2);
  assert.deepEqual(filmSegments(shots).map(segment => segment.seconds), [3, 2, 4, 4], 'nor the film seconds');
  assert.equal(shotStateOf(shots[1]), 'adopted', 'nor the shot state');
  assert.deepEqual(thumbOf(shots[1]).videoUrl, '/take/2.mp4');
});

test('a trial take can stand in for a shot that is not adopted or would be skipped, and keeps its place in the order', () => {
  const shots = [adopted(1), shot(2, {previsVideoUrl: '/previs/2.mp4'}), shot(3), adopted(4)];
  const list = playlist(shots, {fill: 'skip', trial: {shotId: shots[2].shotId, url: '/take/3x.mp4'}});
  assert.deepEqual(list.map(item => [item.shotIndex, item.source]), [['S01', 'adopted'], ['S03', 'trial'], ['S04', 'adopted']]);
  assert.deepEqual(playlist(shots, {trial: {shotId: shots[1].shotId, url: '/take/2x.mp4'}}).map(item => [item.shotIndex, item.url, item.source]),
    [['S01', '/take/1.mp4', 'adopted'], ['S02', '/take/2x.mp4', 'trial'], ['S04', '/take/4.mp4', 'adopted']]);
  assert.deepEqual(playlist(shots, {fill: 'skip', trial: {shotId: 'sh_nope', url: '/x.mp4'}}), playlist(shots, {fill: 'skip'}), 'a trial for a shot that is not in the film is ignored');
  assert.deepEqual(playlist(shots, {fill: 'skip', trial: {shotId: shots[2].shotId, url: ''}}), playlist(shots, {fill: 'skip'}), 'a trial without a url is no trial');
  assert.deepEqual(playlist(shots, {fill: 'skip', trial: null}), playlist(shots, {fill: 'skip'}));
});

test('trying the take that is already adopted keeps its trim', () => {
  const shots = [adopted(1, {trim: {in: 1, out: 2.5}})];
  assert.deepEqual(playlist(shots, {trial: {shotId: shots[0].shotId, url: '/take/1.mp4'}}).map(item => [item.in, item.out, item.source]), [[1, 2.5, 'adopted']]);
});

test('a take is adopted through its proposal when one stands behind it, else as a candidate; a proposal over several rows is not adoptable here', () => {
  const single = rowProposals([mediaProposal(4, 'b1', [{column: 'Cinema Shot', before: '', after: '[Video](/take/4.mp4)'}])], 'b1');
  const shared = mediaProposal(6, 'b1', [{column: 'Cinema Shot', before: '', after: '[Video](/take/6.mp4)'}]);
  shared.review.groups.push({index: 1, row_id: 'b2', row_number: 2, label: 'Row 2', changes: [{column: 'Cinema Shot', before: '', after: '[Video](/take/7.mp4)'}]});
  const several = rowProposals([shared], 'b1');
  const merged = mergeTakes([take(1), take(4)], [...single, ...several]);
  const byUrl = url => merged.find(item => item.url === url);
  assert.deepEqual(adoptionBody(byUrl('/take/4.mp4')), {proposalId: 4}, 'a candidate with a pending proposal goes through the proposal (1.2 K)');
  assert.deepEqual(adoptionBody(byUrl('/take/1.mp4')), {videoId: 'vd_1'});
  assert.equal(adoptionBody(byUrl('/take/6.mp4')), null, 'the adoption endpoint refuses a proposal that edits other rows');
  assert.equal(adoptionBody(null), null);
  assert.deepEqual(adoptionBody({url: '/x.mp4', videoId: 'vd_x', entry: several[0]}), {videoId: 'vd_x'}, 'a known candidate stays adoptable when its proposal spans rows');
});

test('a proposal entry that is only a take is reviewed in the Take list; text, frames or other rows keep it a crew proposal', () => {
  const entry = changes => rowProposals([mediaProposal(3, 'b1', changes)], 'b1')[0];
  const video = {column: 'Cinema Shot', before: '', after: '[Video](/take/3.mp4)'};
  assert.equal(takeOnlyProposal(entry([video])), true);
  assert.deepEqual(proposalTakeUrls(entry([video])), ['/take/3.mp4']);
  assert.equal(takeOnlyProposal(entry([video, {column: 'Prompt', before: 'a', after: 'b'}])), false, 'it also rewrites the prompt');
  assert.equal(takeOnlyProposal(entry([{column: 'Keyframe', before: '', after: '![](/frame/3.png)'}])), false, 'a first frame is not a take');
  assert.equal(takeOnlyProposal({...entry([video]), size: 2}), false, 'it edits another row too');
  assert.equal(takeOnlyProposal(entry([])), false);
  assert.equal(takeOnlyProposal(null), false);
  assert.deepEqual(proposalTakeUrls(entry([{column: 'Prompt', before: 'a', after: 'b'}])), []);
});

test('the adopted count is shots with Approved and a video in the cell, legacy statuses included', () => {
  assert.equal(adoptedCount([adopted(1), adopted(2), shot(3), shot(4, {reviewStatus: 'Pending Review', selectedVideoUrl: '/take/4.mp4'})]), 2);
  assert.equal(adoptedCount([shot(1, {reviewStatus: '已完成', selectedVideoUrl: '/take/1.mp4'})]), 1);
  assert.equal(adoptedCount([shot(1, {reviewStatus: 'Approved'})]), 0, 'Approved with nothing in the cell is not in the film');
  assert.equal(adoptedCount([adopted(1, {takeSummary: {total: 3, newSinceAdoption: 2}}), adopted(2, {reviewStatus: 'Retake'})]), 1, 'a new take keeps it in; a retake takes it out');
  assert.equal(adoptedCount([]), 0);
  assert.equal(adoptedCount(undefined), 0);
  assert.equal(isAdopted(adopted(1)), true);assert.equal(isAdopted(shot(1)), false);assert.equal(isAdopted(null), false);
});
