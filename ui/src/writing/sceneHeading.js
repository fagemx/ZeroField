// The browser copy of the one scene-heading rule (R44-3); project_docs/scene_headings.py is the server's.
// A heading line STARTS with optional literal hashes, an optional scene number ("1.", "1", "12A.", "1)", "#3")
// and Scene N, 場景/场景 N, INT., EXT., INT./EXT. (INT/EXT, EXT./INT.), or the uppercase-only I/E and EST.
// The words never count mid-line. tests/fixtures/scene_heading_cases.json holds both copies to the same answers.
const DIGIT = '[0-9０-９]', END = '(?![0-9A-Za-z_])';
const LEAD = String.raw`^\s*(?:#{1,6}\s*)?(?:#?${DIGIT}{1,4}[A-Za-z]{0,2}(?:[.)]\s*|\s+))?`;
// INT./EXT./Scene stay case-insensitive; I/E and EST. are uppercase only ("Est. 1902" is prose).
// Two expressions instead of a scoped (?-i:) group, which older browsers cannot parse.
const ANY_CASE = new RegExp(LEAD + String.raw`(?:Scene\s*${DIGIT}+|[場场]景\s*[一二三四五六七八九十0-9０-９]+|INT\.?\s*\/\s*EXT${END}\.?|EXT\.?\s*\/\s*INT${END}\.?|INT\.|EXT\.)`, 'i');
const UPPER = new RegExp(LEAD + String.raw`(?:EST\.|I\s*\/\s*E${END}\.?)`);

export const isSceneHeading = line => typeof line === 'string' && (ANY_CASE.test(line) || UPPER.test(line));

export const hasSceneHeadingLine = text => String(text || '').split(/\r\n?|\n/).some(isSceneHeading);
