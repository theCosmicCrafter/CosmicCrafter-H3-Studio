// A generation gets its own sequence folder; old videos/takes never move or get overwritten.
export async function startGeneration({body,snapshot,check,confirm,save,request,apply}) {
  check();
  const before=snapshot();
  const unchanged=()=>{check();if(snapshot()!==before) throw new Error('The project changed. Start a new generation again after edits settle.');};
  if(!await confirm({title:'Start a new generation?',denyLabel:'Cancel',message:
    'Every clip and bridge will start unrendered in a new render folder. Your Timeline, prompts, seeds, settings and references stay as they are. '
    +'The previous generation, including its videos and Takes, is kept. You can play earlier videos from Previous generations below. No rendering starts automatically.'})) return false;
  unchanged();
  await save();unchanged();
  const captured=await body();unchanged();
  const result=await request('/h3c/generations/start',captured);
  if(!result?.ok) throw new Error(result?.error??'Could not start a new generation.');
  unchanged();
  await apply(result);
  return true;
}

export function useGeneration(node,name) {
  const widget=node.widgets?.find(item=>item.name==='name');
  if(!widget) throw new Error('The Timeline has no editable sequence name.');
  for(const [index,input] of (node.inputs??[]).entries())
    if((input.widget?.name??input.name)==='name'&&input.link!=null) node.disconnectInput(index);
  const properties=node.properties??={};
  if(properties.h3c_project||properties.h3c_fork_sequence) properties.h3c_fork_sequence=name;
  delete properties.h3c_project;
  widget.value=name;
}
