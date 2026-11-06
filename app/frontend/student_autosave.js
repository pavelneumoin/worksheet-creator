"use strict";
// One in-flight snapshot; retry the same request after an ambiguous network failure.
class StudentAutosave {
  constructor({read, send, revision=null, onStatus=()=>{}, delay=700}) {
    Object.assign(this,{read,send,revision,onStatus,delay});
    this.changed=0;this.saved=0;this.pending=null;this.saving=null;this.timer=null;
  }
  get dirty(){return this.changed!==this.saved||!!this.saving;}
  edit(){this.changed++;clearTimeout(this.timer);this.onStatus("pending");this.timer=setTimeout(()=>this.flush().catch(()=>{}),this.delay);}
  async flush(){
    clearTimeout(this.timer);
    if(this.saving)return this.saving;
    if(this.changed===this.saved)return;
    this.saving=(async()=>{
      try{
        while(this.changed!==this.saved){
          this.pending??={sequence:this.changed,body:{...this.read(),draft_revision:this.revision,request_id:crypto.randomUUID()}};
          const result=await this.send(this.pending.body);
          this.revision=result.revision;this.saved=this.pending.sequence;this.pending=null;
        }
        this.onStatus("saved");
      }catch(error){this.onStatus("error",error);throw error;}
      finally{this.saving=null;}
    })();
    return this.saving;
  }
  dispose(){clearTimeout(this.timer);}
}
if(typeof module!=="undefined")module.exports={StudentAutosave};
