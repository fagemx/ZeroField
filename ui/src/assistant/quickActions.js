import { t } from '../i18n/index.js';

// SPEC_18 R11: what the crew is offered for where you are and what you hold. Each label names the scene, the card or the shot, and the
// request it sends says the same, so a proposal is about that scene, card or shot and not the whole production. Nothing here writes
// anything: the answer comes back as a proposal and is reviewed where it applies, as every crew proposal is.
// scene {index, title}; asset {code, name}; shot {index}. view: 'script' | 'world' (Story & World only). Returns [{id, label, text}].
export function quickActions({space, view = 'script', scene = null, asset = null, shot = null} = {}) {
  if (space === 'story' && view === 'world') {
    if (!asset) return [];
    const who = {name: asset.name || asset.code, code: asset.code};
    return [{id: 'attributes', label: t('quick.attributes', who), text: t('quick.attributesText', who)},
      {id: 'looks', label: t('quick.looks', who), text: t('quick.looksText', who)}];
  }
  if (space === 'story') {
    const there = scene ? {index: scene.index, title: scene.title} : null;
    return [
      ...(there ? [{id: 'polish', label: t('quick.polish', there), text: t('quick.polishText', there)}] : []),
      {id: 'structure', label: t('quick.structure'), text: t('quick.structureText')},
      {id: 'dialogue', label: t(there ? 'quick.dialogue' : 'quick.dialogueAll', there || {}), text: t(there ? 'quick.dialogueText' : 'quick.dialogueAllText', there || {})},
    ];
  }
  if (space === 'stage' && shot) {
    const which = {shot: shot.index};
    return [{id: 'camera', label: t('quick.camera', which), text: t('quick.cameraText', which)},
      {id: 'continuity', label: t('quick.continuity', which), text: t('quick.continuityText', which)}];
  }
  return [];
}
