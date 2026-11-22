// Saved stories are stored one entry per workflow identity. One story is every entry that renders into the same
// sequence folder, together with every entry that carries the same title (older copies that were given a new, empty
// folder when they were loaded into different wiring). The picker folds them into one group, with each entry a
// numbered version that shows its folder and how many of its clips are rendered, so the copy with the renders is
// easy to find. Nothing is merged on disk or deleted.

const UNTITLED='Untitled story';

// A trailing revision tag such as " · r2" (or " · r3 · r3") marks a revision of the same story, not another story.
const REVISION_TAG=/(?:\s*[·•]\s*r\d+)+$/i;

export function groupKey(title) {
  const text=String(title||UNTITLED).normalize('NFKC').trim().replace(/\s+/g,' ');
  return (text.replace(REVISION_TAG,'').trim()||text).toLocaleLowerCase();
}

// rows: library listing entries ({id,title,sequence,rendered,updated,...}); names: {groupKey: name} the user gave.
// Returns groups newest-activity first; versions inside a group are newest first, numbered from 1 in the order they
// were last saved. A name the user gave replaces the title shown for the group; the group is found by the title key
// of its newest version, or of any of its versions for names given before groups joined folders.
export function groupStories(rows,names={}) {
  const list=[...(rows??[])],parent=list.map((_,index)=>index);
  const find=index=>{while(parent[index]!==index)index=parent[index]=parent[parent[index]];return index;};
  const join=(a,b)=>{a=find(a);b=find(b);if(a!==b)parent[Math.max(a,b)]=Math.min(a,b);};
  for(const field of [row=>'title:'+groupKey(row.title),row=>row.sequence?'folder:'+String(row.sequence).toLocaleLowerCase():null]) {
    const seen=new Map();
    list.forEach((row,index)=>{const key=field(row);if(key==null)return;if(seen.has(key))join(seen.get(key),index);else seen.set(key,index);});
  }
  const groups=new Map();
  list.forEach((row,index)=>{const root=find(index);if(!groups.has(root))groups.set(root,{versions:[]});groups.get(root).versions.push(row);});
  const result=[...groups.values()];
  for(const group of result) {
    group.versions.sort((a,b)=>b.updated-a.updated||String(a.id).localeCompare(String(b.id)));
    group.versions=group.versions.map((row,index)=>({...row,version:group.versions.length-index}));
    const title=String(group.versions[0].title||'').trim().replace(/\s+/g,' ')||UNTITLED;
    group.key=groupKey(group.versions[0].title);
    group.title=title.replace(REVISION_TAG,'').trim()||title;
    const named=[group.key,...group.versions.map(row=>groupKey(row.title))].find(key=>typeof names?.[key]==='string'&&names[key].trim());
    group.name=named?names[named].trim():'';
    group.label=group.name||group.title;
    group.updated=group.versions[0].updated;
    group.folders=new Set(group.versions.map(row=>row.sequence).filter(Boolean)).size;
  }
  return result.sort((a,b)=>b.updated-a.updated||a.label.localeCompare(b.label));
}

export function groupLabel(group) {
  const count=group.versions.length;
  return count>1?`${group.label} · ${count} versions`:group.label;
}

export function versionLabel(row,formatDate=value=>new Date(value*1000).toLocaleString()) {
  const rendered=Number.isInteger(row.rendered)?` · ${row.rendered} rendered`:'';
  const folder=row.sequence?` · ${row.sequence}`:'';
  const label=row.checkpoint_name?`Checkpoint: ${row.checkpoint_name}`:`v${row.version}`;
  return `${label} · ${row.boxes} clips${rendered}${folder} · ${row.status} · ${formatDate(row.updated)}${row.current?' · open now':''}`;
}

// Which group and version to show first: keep the user's choice, else the story open in this workflow, else none.
export function initialSelection(groups,{key,id}={}) {
  const holds=(group,wanted)=>group.versions.some(row=>row.id===wanted);
  const keep=groups.find(group=>group.key===key);
  if(keep)return {key:keep.key,id:holds(keep,id)?id:''};
  const current=groups.find(group=>group.versions.some(row=>row.current));
  if(current)return {key:current.key,id:current.versions.find(row=>row.current).id};
  return {key:'',id:''};
}
