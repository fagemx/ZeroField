// Import submission is assembled separately from the read-only preview request.
function importQuery(target,{format,worksheet='',headerRow=1,deliveryMode='original_patch'}) {
  const query=new URLSearchParams();
  if(target){query.set('tab_key',target.key);query.set('base_revision',target.revision);}
  if(['xlsx','csv'].includes(format)){
    if(!Number.isInteger(Number(headerRow))||Number(headerRow)<1)throw new Error("Enter a valid header row number.");
    query.set('header_row',String(headerRow));
    if(format==='xlsx'&&worksheet)query.set('worksheet',worksheet);
    query.set('delivery_mode',deliveryMode);
  }
  return query;
}
export function importPath(slug,target,options) {
  const query=importQuery(target,options);
  if(target){if(!options.confirmReplace)throw new Error("Confirm that this file should replace the current content.");query.set('confirm_replace','true');}
  return `/projects/api/${slug}/tabs/import${query.size?'?'+query.toString():''}`;
}
export function importPreviewPath(slug,target,options) {
  const query=importQuery(target,options);
  return `/projects/api/${slug}/tabs/import-preview${query.size?'?'+query.toString():''}`;
}
