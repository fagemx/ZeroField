// Import submission is assembled separately from the read-only preview request.
function importQuery(target,{format,worksheet='',headerRow=1,deliveryMode='original_patch'}) {
  const query=new URLSearchParams();
  if(target){query.set('tab_key',target.key);query.set('base_revision',target.revision);}
  if(['xlsx','csv'].includes(format)){
    if(!Number.isInteger(Number(headerRow))||Number(headerRow)<1)throw new Error('請指定有效的表頭列號');
    query.set('header_row',String(headerRow));
    if(format==='xlsx'&&worksheet)query.set('worksheet',worksheet);
    query.set('delivery_mode',deliveryMode);
  }
  return query;
}
export function importPath(slug,target,options) {
  const query=importQuery(target,options);
  if(target){if(!options.confirmReplace)throw new Error('請先確認以這份檔案取代目前內容');query.set('confirm_replace','true');}
  return `/projects/api/${slug}/tabs/import${query.size?'?'+query.toString():''}`;
}
export function importPreviewPath(slug,target,options) {
  const query=importQuery(target,options);
  return `/projects/api/${slug}/tabs/import-preview${query.size?'?'+query.toString():''}`;
}
