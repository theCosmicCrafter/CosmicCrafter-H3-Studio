// The H3 Story face: Write, Check all, Cancel and Undo, Open Studio, and the API keys in a closed section. The Studio
// places the story of the last Write and the export and import row on its Story page.
// Plain DOM without ComfyUI imports; the host object connects it to the node.
import {groupLabel,groupStories,initialSelection,versionLabel} from './h3c_story_groups.mjs?v=734f66b40a7e';
import {ideaImagesRow} from './h3c_idea_images.mjs?v=990e7177d821';
import {decorateIcon} from './h3c_icons.mjs';

const STYLE_ID = 'h3cs-style';
const MIN_HEIGHT = 140;
const STUDIO_TITLE = 'Open the Studio of the linked Timeline on its Story page';
const CSS = `
.h3cs-root { display: flex; flex-direction: column; flex: none; height: fit-content; gap: 6px; width: 100%; overflow-y: auto; box-sizing: border-box; padding: 4px 2px;
  color: var(--input-text, #ddd); font: 13px/1.45 system-ui, sans-serif; }
.h3cs-root * { box-sizing: border-box; }
.h3cs-row { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; min-width: 0; }
.h3cs-button { padding: 2px 8px; font: inherit; color: inherit; white-space: nowrap; cursor: pointer;
  background: var(--comfy-input-bg, #222); border: 1px solid var(--border-color, #444); border-radius: 4px; }
.h3cs-button:hover:not(:disabled) { filter: brightness(1.3); }
.h3cs-button:disabled { opacity: .45; cursor: default; }
.h3cs-button[hidden], .h3cs-story[hidden], .h3cs-part[hidden] { display: none; }
.h3cs-primary { border-color: #5b8fe8; }
.h3cs-keys > summary { cursor: pointer; }
.h3cs-keys-body { display: flex; flex-direction: column; gap: 6px; padding-top: 6px; }
.h3cs-key input { flex: 1 1 140px; min-width: 0; padding: 2px 6px; font: inherit; color: inherit;
  background: var(--comfy-input-bg, #14161a); border: 1px solid var(--border-color, #333); border-radius: 4px; }
.h3cs-message { min-width: 0; }
.h3cs-error { color: #ff8a80; }
.h3cs-hosts, .h3cs-target { font-size: 11px; color: #aab1bd; }
.h3cs-story { display: flex; flex-direction: column; overflow-wrap: anywhere; gap: 4px; padding: 6px;
  background: rgba(0,0,0,.18); border: 1px solid var(--border-color, #333); border-radius: 6px; }
.h3cs-title { font-weight: 600; }
.h3cs-part { display: flex; flex-direction: column; gap: 2px; }
.h3cs-heading { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: #aab1bd; }
.h3cs-sheet { white-space: pre-wrap; user-select: text; cursor: text; }
.h3cs-suggestions, .h3cs-notes { display: flex; flex-direction: column; gap: 2px; }
.h3cs-outline { display: flex; flex-direction: column; gap: 1px; margin: 0; padding: 0; list-style: none; }
.h3cs-beat { display: flex; align-items: baseline; gap: 10px; width: 100%; padding: 6px 8px; font: inherit; color: inherit; text-align: left;
  background: transparent; border: 0; border-radius: 5px; cursor: pointer; }
.h3cs-beat:hover { background: #ffffff0d; }
.h3cs-beat:focus-visible { outline: 2px solid #8fbcff; outline-offset: -2px; }
.h3cs-beat[aria-current=true] { background: #2a3a55; }
.h3cs-clip-number { flex: 0 0 auto; min-width: 22px; padding: 0 5px; border-radius: 4px; background: #ffffff12; color: #c9d1dd;
  font-size: 11px; font-variant-numeric: tabular-nums; line-height: 18px; text-align: center; }
.h3cs-beat-text { min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.h3cs-beat[aria-current=true] .h3cs-beat-text { white-space: normal; }
.h3cs-file-group { gap: 6px; }
.h3cs-notes { font-size: 11px; color: #e6c07b; }
.h3cs-settings { display: flex; flex-direction: column; flex: none; width: 100%; height: fit-content;
  box-sizing: border-box; color: var(--input-text, #ddd); font: 13px/1.45 system-ui, sans-serif; }
.h3cs-settings * { box-sizing: border-box; }
.h3cs-settings-body { display: flex; flex-direction: column; gap: 8px; padding-top: 6px; }
.h3cs-settings .h3cx-field { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.h3cs-library { width:100%; min-width:0; }
.h3cs-library > summary { cursor:pointer; font-weight:600; }
.h3cs-library select { display:block; margin-top:6px; width:100%; min-width:0; padding:5px; color:inherit; background:var(--comfy-input-bg,#222); }
.h3cs-library .h3cs-row { margin-top:6px; }
`;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function button(label, title, onClick, className = '', iconName = null) {
  const node = el('button', `h3cs-button ${className}`.trim(), label);
  node.type = 'button';
  if (iconName) decorateIcon(node, iconName, label, {text: true});
  node.title = title;
  node.addEventListener('click', (event) => {
    event.preventDefault();
    onClick();
  });
  return node;
}

function part(heading, body) {
  const node = el('div', 'h3cs-part');
  node.append(el('div', 'h3cs-heading', heading), body);
  return node;
}

function injectStyle() {
  if (document.getElementById(STYLE_ID)) return;
  const style = el('style');
  style.id = STYLE_ID;
  style.textContent = CSS;
  document.head.append(style);
}

function suggestionText(item, numberOf) {
  const numbers = item.boxes.map(numberOf).filter((n) => n != null).sort((a, b) => a - b);
  const where = numbers.length ? ` (${numbers.length === 1 ? 'clip' : 'clips'} ${numbers.join(', ')})` : '';
  const detail = [item.description, item.why].filter(Boolean).join(' ');
  return detail ? `${item.what}${where}: ${detail}` : `${item.what}${where}`;
}

export class StoryPanel {
  // host: write(), rewrite(), checkAll(), cancel(), undo(), saveKey(key), forgetKey() and openStudio().
  constructor(host) {
    injectStyle();
    this.host = host;
    this.root = el('div', 'h3cs-root');
    this.root.addEventListener('pointerdown', (event) => event.stopPropagation());
    this.root.addEventListener('keydown', (event) => {
      if (!event.ctrlKey && !event.metaKey && !event.altKey) event.stopPropagation();
    });
    this.writeButton = button('Write story', 'Plan the story and write clip prompts in scope. Generate clips separately in the Timeline.',
      () => host.write(), 'h3cs-primary', 'write');
    this.boxButton = button('Rewrite selected clip',
      'Write prompts only for the selected Timeline clip, preserving its storyline and both neighbors. Generate the clip separately.',
      () => host.write(true), 'h3cs-box-button', 'write');
    this.rewriteButton = button('Rewrite all clips',
      'Rewrite every clip prompt, including rendered clips and manual edits; keep clips and timing. Undo restores the previous prompts. Generate clips separately.',
      () => host.rewrite(), '', 'rewrite');
    this.checkAllButton = button('Check rendered clips', "Check every rendered clip that has no current check with the Story's "
      + "Vision model, then unload it; ComfyUI's queue must be empty", () => host.checkAll(), '', 'check');
    this.cancelButton = button('Cancel', 'Stop the Write or the check; what it finished is kept', () => host.cancel(), '', 'stop');
    this.undoButton = button('Undo last Write', 'Put back the prompts the last Write replaced', () => host.undo(), '', 'undo');
    this.messageEl = el('span', 'h3cs-message');
    this.keepWorkflowButton = button('Keep this workflow',
      'Save this workflow and its current prompts as an independent story. The previously saved story stays unchanged.',
      () => host.keepWorkflow?.(), '', 'save');
    this.keepWorkflowButton.hidden = true;
    this.actionsEl = el('div', 'h3cs-row h3cs-actions');
    this.actionsEl.append(this.writeButton, this.boxButton, this.rewriteButton, this.checkAllButton,
      this.cancelButton, this.undoButton, this.keepWorkflowButton, this.messageEl);

    this.filesEl = el('div', 'h3cs-row');
    this.exportButton = button('Export project', 'Download the Story, Timeline and complete workflow wiring as project JSON. Media and RefMods stay file references; this does not download video.',
      () => host.exportStory?.(), '', 'download');
    this.importInput = el('input');
    this.importInput.type = 'file';
    this.importInput.accept = '.json,application/json';
    this.importInput.hidden = true;
    this.importInput.addEventListener('change', () => {
      const file = this.importInput.files?.[0];
      this.importInput.value = '';
      if (file) host.importStory?.(file);
    });
    const projectFiles = el('div', 'h3cs-row h3cs-file-group');
    projectFiles.append(this.exportButton, button('Import project', 'Restore project JSON and workflow wiring in a new workflow tab. Media and RefMods remain file references.',
      () => this.importInput.click(), '', 'upload'), this.importInput);

    const generationInput=el('input');generationInput.type='file';generationInput.accept='.json,application/json';generationInput.hidden=true;
    generationInput.addEventListener('change',()=>{const file=generationInput.files?.[0];generationInput.value='';if(file)host.importGeneration?.(file);});
    const generationFiles=el('div','h3cs-row h3cs-file-group');
    generationFiles.append(button('Export generation','Transfer Story, guides, candidates and saved takes to another generator workflow.',()=>host.exportGeneration?.(),'','download'),
      button('Import generation','Keep this workflow and generator; import a verified independent generation into it.',()=>generationInput.click(),'','upload'),generationInput,
      button('Fork as a copy','Download this generation as a file, then keep working on a copy with all its renders and takes, to try another continuation without changing this one.',()=>host.forkGeneration?.(),'','duplicate'));
    this.filesEl.append(projectFiles, generationFiles);

    this.keyInput = el('input');
    this.keyInput.type = 'password';
    this.keyInput.autocomplete = 'new-password';
    this.keyInput.spellcheck = false;
    this.keyInput.placeholder = "API key for the Box URL's host";
    const key = el('div', 'h3cs-row h3cs-key');
    key.append(this.keyInput,
      button('Save', "Save the key on the ComfyUI server for the Box API URL's host", () => this.saveKey()),
      button('Forget', "Delete the saved key of the Box API URL's host", () => host.forgetKey()));
    this.hostsEl = el('div', 'h3cs-hosts');
    const storyKey = el('div', 'h3cs-row h3cs-key');
    this.storyKeyInput = el('input');
    this.storyKeyInput.type = 'password';
    this.storyKeyInput.autocomplete = 'new-password';
    this.storyKeyInput.placeholder = "API key for the Story URL's host";
    storyKey.append(this.storyKeyInput,
      button('Save Story key', 'Save the key for the Story API host; an empty Story URL uses the Box URL', () => {
        host.saveStoryKey?.(this.storyKeyInput.value);
        this.storyKeyInput.value = '';
      }),
      button('Forget Story key', 'Delete the saved Story API key', () => host.saveStoryKey?.('')));
    const visionKey = el('div', 'h3cs-row h3cs-key');
    this.visionKeyInput = el('input');
    this.visionKeyInput.type = 'password';
    this.visionKeyInput.autocomplete = 'new-password';
    this.visionKeyInput.placeholder = "API key for the Vision URL's host";
    visionKey.append(this.visionKeyInput,
      button('Save Vision key', 'Save the key for the Vision API host', () => {
        host.saveVisionKey?.(this.visionKeyInput.value);
        this.visionKeyInput.value = '';
      }),
      button('Forget Vision key', 'Delete the saved Vision API key', () => host.saveVisionKey?.('')));
    this.keysSummaryEl = el('summary', null, 'API keys');
    const keysBody = el('div', 'h3cs-keys-body');
    keysBody.append(key, storyKey, visionKey, this.hostsEl);
    this.keysEl = el('details', 'h3cs-keys');
    this.keysEl.append(this.keysSummaryEl, keysBody);

    this.studioButton = button('Open Studio', STUDIO_TITLE, () => host.openStudio?.(), '', 'viewer');
    this.targetEl = el('div', 'h3cs-target');
    const studio = el('div', 'h3cs-row');
    studio.append(this.studioButton, this.targetEl);

    this.storyEl = el('div', 'h3cs-story');
    this.titleEl = el('div', 'h3cs-title');
    this.outlineEl = el('ol', 'h3cs-outline');
    this.sheetEl = el('div', 'h3cs-sheet');
    this.suggestionsEl = el('div', 'h3cs-suggestions');
    this.notesEl = el('div', 'h3cs-notes');
    this.draftsEl = el('div', 'h3cs-drafts');
    this.outlinePart = part('Outline', this.outlineEl);
    this.sheetPart = part('Continuity sheet', this.sheetEl);
    this.suggestionsPart = part('Suggested references', this.suggestionsEl);
    this.storyEl.append(this.titleEl, this.outlinePart, this.sheetPart, this.suggestionsPart, this.notesEl, this.draftsEl);
    this.root.append(this.actionsEl, studio, this.keysEl);
    if(host.listStories) {
      this.libraryEl=el('details','h3cs-library');
      this.libraryEl.append(el('summary',null,'Saved stories'));
      // Story = every saved entry sharing a title; Version = one saved entry of it.
      this.libraryGroup=el('select');this.libraryGroup.setAttribute('aria-label','Saved story');
      this.librarySelect=el('select');this.librarySelect.setAttribute('aria-label','Saved story version');
      this.libraryGroups=[];this.libraryRows=[];
      this.libraryNote=el('span','h3cs-hosts','Saved on this ComfyUI server.');
      const row=el('div','h3cs-row'),storyRow=el('div','h3cs-row');
      this.libraryOpen=button('Load version','Load an autosaved version into this Timeline, or open a named checkpoint as an independent editable workflow with its videos.',()=>host.openSavedStory(this.librarySelect.value),'h3cs-primary','upload');
      this.libraryDelete=button('Delete version','Delete the selected version and its generated media. Other versions of the story are kept.',()=>host.deleteSavedStory(this.libraryRows.find(row=>row.id===this.librarySelect.value)),'','trash');
      this.libraryRename=button('Rename story','Give the selected story a name instead of its title.',()=>host.renameSavedStory(this.selectedGroup()),'','write');
      this.libraryDeleteStory=button('Delete story','Delete every version of the selected story and its generated media.',()=>host.deleteSavedStoryGroup(this.selectedGroup()),'','trash');
      row.append(this.libraryOpen,this.libraryDelete,button('Refresh','Refresh stories saved on this server.',()=>this.refreshStories(),'','history'));
      storyRow.append(this.libraryRename,this.libraryDeleteStory);
      const saveRow=el('div','h3cs-row');
      this.checkpointButton=button('Save checkpoint…','Save a named snapshot of this workflow, Timeline and rendered videos. Later edits keep this checkpoint intact.',()=>host.saveCheckpoint?.(),'','save');
      saveRow.append(this.checkpointButton);
      if(host.autosaveEnabled) {
        const label=el('label','h3cs-row');
        this.autosaveInput=el('input');this.autosaveInput.type='checkbox';
        this.autosaveInput.checked=host.autosaveEnabled();
        label.append(this.autosaveInput,el('span',null,'Autosave'));
        label.title='Automatically save Story and Timeline edits for all workflows. Named checkpoints are always kept separately.';
        this.autosaveInput.addEventListener('change',async()=>{
          this.autosaveInput.disabled=true;
          try {await host.setAutosave(this.autosaveInput.checked);
            this.say(this.autosaveInput.checked?'Autosave on.':'Autosave off. Save a checkpoint to keep your edits and videos.');}
          catch(error) {this.say(error.message,true);}
          finally {this.autosaveInput.checked=host.autosaveEnabled();this.autosaveInput.disabled=false;}
        });
        saveRow.append(label);
      }
      this.libraryEl.append(saveRow,this.libraryGroup,this.librarySelect,row,storyRow,this.libraryNote);
      this.libraryEl.addEventListener('toggle',()=>{if(this.libraryEl.open)this.refreshStories();});
      this.root.insertBefore(this.libraryEl,this.keysEl);
      this.libraryGroup.addEventListener('change',()=>this.showVersions(this.libraryGroup.value));
      this.librarySelect.addEventListener('change',()=>this.syncLibraryButtons());
      this.syncLibraryButtons();
    }
    this.settingFields = new Map();
    this.settingValues = new Map();
    if (host.settings) {
      this.settingsEl = el('div', 'h3cs-settings');
      this.settingsBody = el('div', 'h3cs-settings-body');
      this.settingsEl.append(this.settingsBody);
    }
    this.idle(false);
    this.showStory(null);
  }

  saveKey() {
    const key = this.keyInput.value.trim();
    this.keyInput.value = '';
    if (!key) {
      this.say('Paste a key first.', true);
      return;
    }
    this.host.saveKey(key);
  }

  async refreshStories() {
    if(this.autosaveInput)this.autosaveInput.checked=this.host.autosaveEnabled();
    this.libraryNote.textContent='Loading saved stories…';
    try {
      const wanted={key:this.libraryGroup.value,id:this.librarySelect.value};
      const {rows,names}=await this.host.listStories();
      this.libraryRows=rows;
      this.libraryGroups=groupStories(rows,names);
      this.libraryGroup.replaceChildren();
      const placeholder=el('option',null,this.libraryGroups.length?'Choose a saved story':'No saved stories yet');placeholder.value='';
      this.libraryGroup.append(placeholder);
      for(const group of this.libraryGroups) {
        const option=el('option',null,groupLabel(group));option.value=group.key;this.libraryGroup.append(option);
      }
      const start=initialSelection(this.libraryGroups,wanted);
      this.libraryGroup.value=start.key;
      this.showVersions(start.key,start.id);
      this.libraryNote.textContent='Saved on this ComfyUI server. Current edits are saved before switching.';
    } catch(error) {
      this.libraryNote.textContent=error.message;this.libraryGroups=[];this.libraryRows=[];
      this.showVersions('');
    }
  }

  selectedGroup() {return this.libraryGroups.find(group=>group.key===this.libraryGroup.value);}

  showVersions(key,id='') {
    const group=this.libraryGroups.find(group=>group.key===key);
    this.librarySelect.replaceChildren();
    this.libraryGroup.disabled=!this.libraryGroups.length;
    this.librarySelect.disabled=!group;
    const placeholder=el('option',null,group?'Choose a version':'Choose a story first');placeholder.value='';
    this.librarySelect.append(placeholder);
    for(const row of group?.versions??[]) {
      const option=el('option',null,versionLabel(row));option.value=row.id;this.librarySelect.append(option);
    }
    // A story with a single version needs no second choice; otherwise the newest version with rendered clips comes first.
    const rendered=group?.versions.find(row=>row.rendered>0);
    this.librarySelect.value=group?.versions.some(row=>row.id===id)?id:group?.versions.length===1?group.versions[0].id:rendered?.id??'';
    this.syncLibraryButtons();
  }

  syncLibraryButtons() {
    this.libraryOpen.disabled=this.libraryDelete.disabled=!this.librarySelect.value;
    this.libraryRename.disabled=this.libraryDeleteStory.disabled=!this.selectedGroup();
  }

  busy(progress) {
    this.exportButton.disabled = true;
    this.writeButton.disabled = true;
    this.boxButton.disabled = true;
    this.rewriteButton.disabled = true;
    this.checkAllButton.disabled = true;
    this.cancelButton.hidden = false;
    this.undoButton.disabled = true;
    this.undoButton.title = 'Undo is available after writing finishes';
    this.say(progress);
  }

  idle(canUndo) {
    this.exportButton.disabled = false;
    this.writeButton.disabled = false;
    this.boxButton.disabled = false;
    this.rewriteButton.disabled = false;
    this.checkAllButton.disabled = false;
    this.cancelButton.hidden = true;
    this.undoButton.disabled = !canUndo;
    this.undoButton.title = canUndo ? 'Put back the prompts the last Write replaced' : 'No saved Write to undo in this Story node';
  }

  say(text, error = false) {
    this.messageEl.textContent = text ?? '';
    this.messageEl.classList.toggle('h3cs-error', Boolean(error));
  }

  showLibraryConflict(show) {
    this.keepWorkflowButton.hidden = !show;
  }

  showHosts(hosts) {
    if (hosts == null) this.hostsEl.textContent = '';
    else this.hostsEl.textContent = hosts.length ? `Keys saved for ${hosts.join(', ')}.` : 'No keys saved.';
    this.keysSummaryEl.textContent = hosts == null ? 'API keys'
      : hosts.length ? `API keys · saved for ${hosts.join(', ')}` : 'API keys · none saved';
  }

  showTarget(text) {
    this.targetEl.textContent = text ?? '';
  }

  // reason: why Open Studio cannot open a Studio from this Story, or null when it can.
  showStudio(reason) {
    this.studioButton.disabled = reason != null;
    this.studioButton.title = reason ?? STUDIO_TITLE;
  }

  // state: the parsed story state, or null. numberOf(id): the box's number in the Timeline now, or null.
  showStory(state, numberOf = () => null) {
    const outline = (state?.outline ?? []).map((item) => [numberOf(item.box), item.beat, item.box])
      .filter(([number]) => number != null).sort((a, b) => a[0] - b[0]);
    const suggestions = state?.suggestions ?? [];
    const notes = state?.notes ?? [];
    this.titleEl.textContent = state?.title ?? '';
    this.outlineEl.replaceChildren(...outline.map(([number, beat, box]) => {
      const row = el('li', 'h3cs-beat-row');
      const pick = el('button', 'h3cs-beat');
      pick.type = 'button';
      pick.dataset.box = box;
      pick.title = `Clip ${number}: ${beat}`;
      pick.append(el('span', 'h3cs-clip-number', String(number)), el('span', 'h3cs-beat-text', beat));
      pick.addEventListener('click', () => this.onSelectBox?.(box));
      row.append(pick);
      return row;
    }));
    this.markBox(this.markedBox);
    this.sheetEl.textContent = state?.sheet ?? '';
    this.suggestionsEl.replaceChildren(...suggestions.map((item) => el('div', null, suggestionText(item, numberOf))));
    this.notesEl.replaceChildren(...notes.map((note) => el('div', null, note)));
    const drafts = Object.entries(state?.drafts ?? {});
    this.draftsEl.replaceChildren(...drafts.map(([id, draft]) => {
      const details = el('details');
      const label = id === 'plan' ? 'Story plan' : id === 'revision' ? 'Revision' : `Clip ${numberOf(id) ?? id}`;
      const content = el('pre', null, draft.reply ?? '');
      content.style.cssText = 'white-space:pre-wrap;overflow-wrap:anywhere;max-height:240px;overflow:auto';
      details.append(el('summary', null, `${label} draft`), el('div', null, draft.error ?? ''), content);
      return details;
    }));
    this.outlinePart.hidden = !outline.length;
    this.sheetPart.hidden = !this.sheetEl.textContent;
    this.suggestionsPart.hidden = !suggestions.length;
    this.storyEl.hidden = !(this.titleEl.textContent || outline.length || this.sheetEl.textContent
      || suggestions.length || notes.length || drafts.length);
    this.onShowStory?.();
  }

  // id: the selected Timeline clip, shown expanded in the outline.
  markBox(id) {
    this.markedBox = id;
    for (const pick of [...this.outlineEl.children].map((row) => row.firstChild)) {
      if (pick.dataset.box === id) pick.setAttribute('aria-current', 'true');
      else pick.removeAttribute('aria-current');
    }
  }

  height() {
    return Math.max(MIN_HEIGHT, this.root.scrollHeight);
  }

  settingsHeight() { return this.settingsEl?.scrollHeight ?? 0; }

  refreshSettings() {
    if (!this.settingsEl) return;
    for (const input of this.host.settings()) {
      const signature = JSON.stringify([input.value, input.linked]);
      if (this.settingValues.get(input.name) === signature) continue;
      let field = this.settingFields.get(input.name);
      if (!field) {
        field = el('div', 'h3cx-field');
        this.settingFields.set(input.name, field);
        this.settingsBody.append(field);
      }
      this.settingValues.set(input.name, signature);
      const label = el('span', 'h3cx-label', input.label);
      const set = value => {
        this.settingValues.set(input.name, JSON.stringify([value, input.linked]));
        this.host.setInput(input.name, value);
      };
      field.replaceChildren(label, input.linked != null ? el('p', 'h3cx-linked', `Linked from ${input.linked}`)
        : ideaImagesRow(input, set));
    }
  }

  settingField(name) {
    this.refreshSettings();
    return this.settingFields.get(name);
  }
}
