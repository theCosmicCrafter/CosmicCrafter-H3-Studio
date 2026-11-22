// Read-only preflight. The returned consent belongs only to the queued replacement, never the saved Timeline.
export async function confirmRegeneration({body,box,count=1,request,confirm,snapshot}) {
  const before=snapshot();
  const check=await request('/h3c/timeline/regeneration',{...body,box});
  const unchanged=()=>{if(snapshot()!==before) throw new Error('The Timeline changed; generate this clip again to review its affected clips.');};
  unchanged();
  if(!check?.ok) throw new Error(check?.error??'Could not check saved continuity. Try again.');
  if(!check.needs_rebuild) return {cancelled:false,receipt:null};
  if(count!==1) throw new Error('Rebuild continuity with one take first. Select 1 take, then generate this clip again.');
  const numbers=check.affected.map(item=>item.number);
  const listed=numbers.length>1?`${numbers.slice(0,-1).join(', ')} and ${numbers.at(-1)}`:String(numbers[0]);
  const clips=`${numbers.length===1?'Clip':'Clips'} ${listed}`;
  let message=`${check.reason}\n\nIf you continue, ${clips} will be marked as needing a render and removed from the current assembled video `
    +`after clip ${check.number} successfully saves. Their existing videos will be kept in Takes. `
    +'Cancelling or a failed render leaves the existing videos in place.\n\nUse Render remaining afterward to rebuild those clips and restore the complete video.';
  if(check.bridges?.length) message+='\n\nAffected bridges will also be kept in Takes and need a new render.';
  if(check.replacements?.length) message+='\n\nAffected replacement regions will need review and a new candidate; existing candidates are kept.';
  const accepted=await confirm({title:`Regenerate clip ${check.number} and rebuild continuity?`,message,denyLabel:'Cancel'});
  if(!accepted) return {cancelled:true,receipt:null};
  unchanged();
  return {cancelled:false,receipt:check.receipt};
}
