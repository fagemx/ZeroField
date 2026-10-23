import { mutationId } from './writingTransport.js';
export async function waitWritingTextTask(request,task,{signal,onProgress}={}) {
  while(['QUEUED','RUNNING'].includes(task.status)){
    if(signal?.aborted)throw new DOMException('Aborted','AbortError');
    onProgress?.(task);
    await new Promise((resolve,reject)=>{
      const abort=()=>{clearTimeout(timer);reject(new DOMException('Aborted','AbortError'));};
      const timer=setTimeout(()=>{signal?.removeEventListener('abort',abort);resolve();},800);
      signal?.addEventListener('abort',abort,{once:true});
    });
    task=await request(`/tasks/${encodeURIComponent(task.taskId)}`,'GET',undefined,{signal});
  }
  if(task.status!=='SUCCEEDED')throw new Error(task.error?.message || task.status);
  return task.result;
}
export function createTextStoryboardAction(request,epId,{breakdownMode='auto',signal,onProgress}={}) {
  // Per-step keys survive an ambiguous response and are never shared with another action.
  const extractKey=mutationId(),buildKey=mutationId();let extraction,extracted=false,storyboard;
  return async()=>{
    if(!extracted){extraction ||= await request(`/episodes/${encodeURIComponent(epId)}/asset-extractions`,'POST',{}, {idempotencyKey:extractKey,signal});await waitWritingTextTask(request,extraction,{signal,onProgress});extracted=true;}
    storyboard ||= await request(`/episodes/${encodeURIComponent(epId)}/storyboards`,'POST',{breakdownMode},{idempotencyKey:buildKey,signal});
    return waitWritingTextTask(request,storyboard,{signal,onProgress});
  };
}
