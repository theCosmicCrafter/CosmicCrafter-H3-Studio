const terminal = new Set(['complete','failed','cancelled']);

export class ImageJobClient {
  constructor({request,capture,receipts,save,context,identify,resultPath='/h3c/stills/result'}) {
    Object.assign(this,{request,capture,receipts,context,identify,resultPath});
    if(save)this.save=save;
    this.active=new Set();
  }
  async generate(request) {
    const context=this.context?.();
    const prepared=await this.capture(structuredClone(request));
    if(context!==this.context?.())throw Error("The generation changed during still preparation.");
    const receipt={request_id:prepared.request.request_id,prompt_id:prepared.prompt_id,...this.identify(prepared),state:'submitting',provenance:structuredClone(prepared.provenance)};
    this.active.add(receipt.prompt_id);
    try {await this.save(receipt,context);} catch(error) {this.active.delete(receipt.prompt_id);throw error;}
    const metadata={request_id:receipt.request_id,prompt_id:receipt.prompt_id,provenance:receipt.provenance,collector:'h3c_still_output'};
    try {
      const queued=await this.request('/prompt',{prompt_id:receipt.prompt_id,prompt:prepared.prompt,
        partial_execution_targets:prepared.outputs,extra_data:{h3c_still:metadata,
          extra_pnginfo:{workflow:prepared.request.workflow.ui,h3c_still:metadata}}});
      receipt.state=queued.error?'failed':queued.prompt_id===receipt.prompt_id?'queued':'unknown';
      if(queued.error) receipt.error=typeof queued.error==='string'?queued.error:queued.error.message;
    } catch(error) {receipt.state='unknown';receipt.error=error.message;}
    try {return await this.save(receipt,context);} finally {this.active.delete(receipt.prompt_id);}
  }
  // Resolves to how many receipts the server changed.
  async recover() {
    if(this.recovering) return this.recovering;
    this.recovering=this.readResults();
    try {return await this.recovering;} finally {this.recovering=null;}
  }
  async readResults() {
    const context=this.context?.();
    const receipts=structuredClone(this.receipts()??[]);
    let changed=0;
    for(const receipt of receipts) {
      if(terminal.has(receipt.state) || this.active.has(receipt.prompt_id)) continue;
      const before=JSON.stringify(receipt);
      try {
        const result=await this.request(this.resultPath,receipt);
        if(!result.ok) {receipt.state='unknown';receipt.error=result.error;}
        else {
          receipt.state=result.state;delete receipt.error;
          if(result.state==='complete') receipt.images=result.images.map(image=>({...structuredClone(receipt.provenance),
            file:image.file,...(image.sha256?{sha256:image.sha256}:{}),request_id:receipt.request_id,prompt_id:receipt.prompt_id,batch_index:image.batch_index}));
        }
      } catch(error) {receipt.state='unknown';receipt.error=error.message;}
      const current=this.receipts()?.find(item=>item.request_id===receipt.request_id&&item.prompt_id===receipt.prompt_id);
      if(context!==this.context?.()||!current||current.historical||terminal.has(current.state))continue;
      // A request the server has nothing new about stays as it is: saving it again would rewrite and reload the whole
      // Timeline each time it is checked, which is after every edit.
      if(JSON.stringify(receipt)===before)continue;
      await this.save(receipt,context,{recovered:true});
      changed++;
    }
    return changed;
  }
}
