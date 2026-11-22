// Reset authored Timeline content; uploaded pictures and source configuration stay available.
export function freshProject(text) {
 let old;
 try { old = JSON.parse(text); } catch { throw new Error('Repair the Timeline JSON before starting a project.'); }
 if (!old || typeof old !== 'object' || Array.isArray(old)) throw new Error('Repair the Timeline JSON before starting a project.');
 const timeline = {version:1,prompt:'',boxes:[]};
 for (const key of ['pictures','refmods','qwen']) if (old[key] != null) timeline[key] = old[key];
 return {name:`Project-${crypto.randomUUID().slice(0,8)}`,timeline:JSON.stringify(timeline)};
}
