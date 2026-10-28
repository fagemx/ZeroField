import { t } from '../i18n/index.js';
import { mediaOf } from '../sheetModel.js';

// The server describes a change in neutral parts (kind, row_number, context, column_kind);
// the words come from the locale files so the English UI never shows Chinese.
export function reviewGroupLabel(group) {
  if (!group?.kind) return group?.label || ''; // reviews stored before `kind` existed keep their saved label
  const row = group.row_number ? t('tableProposalReview.rowNumber', { n: group.row_number }) + ' · ' : '';
  const fallback = group.kind === 'structure' ? t('tableProposalReview.structureChange') : t('tableProposalReview.newData');
  return (row + (group.context || fallback)).slice(0, 200);
}

export function reviewColumnLabel(change) {
  if (change?.column_kind === 'structure') return t('tableProposalReview.documentStructure');
  if (change?.column_kind === 'index') return t('tableProposalReview.columnNumber', { n: Number(change.column_index ?? 0) + 1 });
  return change?.column ?? '';
}

const MEDIA_LABEL = { image: 'imageCell', video: 'videoCell', audio: 'audioCell', asset: 'assetCell' };

// A cell holding media is stored as markdown text; show the picture or a label, never the markdown.
export function reviewMedia(value) {
  const media = mediaOf(value);
  return media ? { ...media, label: t('tableProposalReview.' + MEDIA_LABEL[media.kind]) } : null;
}
