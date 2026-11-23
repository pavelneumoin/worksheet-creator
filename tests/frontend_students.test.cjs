"use strict";
const {test}=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const source=fs.readFileSync(path.join(__dirname,"../app/frontend/students.js"),"utf8");
const helpers=source.slice(source.indexOf("function pupilCategory("),source.indexOf("function pupilBadge("));
const model=vm.createContext({});vm.runInContext(helpers,model);

test("a new attempt takes priority over an older confirmed result",()=>{
  const previous={score:2,max_score:4};
  assert.equal(model.pupilCategory({result:previous,attempts:[{status:"returned"}],can_submit:true}),"returned");
  for(const status of ["submitted","processing","needs_review"]){assert.equal(model.pupilCategory({result:previous,attempts:[{status}]}),"waiting");}
  assert.equal(model.pupilCategory({result:previous,attempts:[{status:"confirmed"}]}),"confirmed");
  assert.equal(model.pupilCategory({result:previous,attempts:[]}),"confirmed");
});
test("closed assignments never appear in the submit queue",()=>{
  assert.equal(model.pupilCategory({attempts:[],can_submit:false}),"closed");
  assert.equal(model.pupilCategory({attempts:[],can_submit:true}),"todo");
  const queue=[{attempts:[{status:"confirmed"}]},{can_submit:true},{attempts:[{status:"returned"}]}].sort((a,b)=>model.pupilPriority(a)-model.pupilPriority(b));
  assert.deepEqual(queue.map(model.pupilCategory),["returned","todo","confirmed"]);
});
test("progress is based on scored tasks and remains empty without results",()=>{
  assert.equal(model.pupilPercentage(2.5,4),63);
  assert.equal(model.pupilPercentage(0,0),null);
  assert.equal(model.pupilPercentage(undefined,3),null);
  assert.equal(model.pupilPercentage(5,4),100);
});
test("an old returned attempt stops appearing as an outstanding correction",()=>{
  const attempts=[{id:"old",assignment_id:"one",student_id:"pupil",number:1,status:"returned"},{id:"new",assignment_id:"one",student_id:"pupil",number:2,status:"confirmed"},{id:"other",assignment_id:"two",student_id:"pupil",number:1,status:"returned"}];
  const latest=model.pupilLatestAttempts(attempts);assert.deepEqual(Array.from(latest,a=>a.id),["new","other"]);assert.equal(latest.filter(a=>a.status==="returned").length,1);
});
test("student views highlight the matching role and clear it on navigation",()=>{
  const script=fs.readFileSync(path.join(__dirname,"../app/frontend/script.js"),"utf8"),elements=new Map();
  const field=id=>{if(!elements.has(id))elements.set(id,{value:"",classList:{toggle:(name,active)=>{elements.get(id)[name]=active;}}});return elements.get(id);};
  const c=vm.createContext({state:{view:"workspace",files:[],studentMode:"pupil"},$:field,window:{scrollTo(){}}});
  vm.runInContext(script.slice(script.indexOf("function showView("),script.indexOf("async function request(")),c);
  c.showView("student",false);assert.equal(field("studentNav").active,true);assert.equal(field("studentInboxNav").active,false);assert.equal(field("mobileMoreNav").active,true);
  c.state.studentMode="teacher";c.showView("student",false);assert.equal(field("studentNav").active,false);assert.equal(field("studentInboxNav").active,true);
  c.showView("feedback",false);assert.equal(field("studentInboxNav").active,false);assert.equal(field("mobileMoreNav").active,true);
  c.showView("workspace",false);assert.equal(field("studentNav").active,false);assert.equal(field("mobileMoreNav").active,false);
});
test("file validation matches PDF/photo constraints before upload",()=>{
  const file=(name,size=1024)=>({name,size});
  assert.equal(model.pupilUploadError([file("работа.PDF")]),"");
  assert.equal(model.pupilUploadError([file("1.jpg"),file("2.PNG")]),"");
  assert.match(model.pupilUploadError([file("1.pdf"),file("2.jpg")]),/отдельно/);
  assert.match(model.pupilUploadError([file("1.pdf"),file("2.pdf")]),/отдельно/);
  assert.match(model.pupilUploadError([file("script.svg")]),/JPEG/);
  assert.match(model.pupilUploadError(Array.from({length:11},()=>file("1.jpg"))),/10/);
  assert.match(model.pupilUploadError([file("1.jpg",16*1024*1024)]),/15/);
  assert.match(model.pupilUploadError([file("1.jpg",11*1024*1024),file("2.jpg",11*1024*1024)]),/20/);
});

function uploadFixture(request,openAssignment=async()=>{}){
  class Element{
    constructor(tag,text,classes){this.tagName=tag;this.textContent=text;this.classes=classes||"";this.children=[];this.events={};this.classList={add(){},remove(){}};}
    append(...items){this.children.push(...items);}
    replaceChildren(...items){this.children=[...items];}
    setAttribute(){}
    addEventListener(type,callback){this.events[type]=callback;}
    click(){return this.events.click?.();}
  }
  const view=new Element("section"),work=[],calls=[];let serial=0;
  const context=vm.createContext({node:(...args)=>new Element(...args),classButton:(label,callback,kind)=>{const button=new Element("button",label,kind);button.addEventListener("click",callback);return button;},pupilView:view,crypto:{randomUUID:()=>"key-"+(++serial)},FormData:class{append(){}},request:async(url,options)=>{calls.push(options);return request(url,options);},openStudentAssignment:openAssignment,notice:()=>{},busy:(_,action)=>{const promise=action();work.push(promise);promise.catch(()=>{});}});
  vm.runInContext(helpers+source.slice(source.indexOf("function renderPupilUpload("),source.indexOf("async function showPupilInvite(")),context);
  context.renderPupilUpload({},"assignment",null);
  const form=view.children[0],file=form.children.find(x=>x.tagName==="input"&&x.multiple),submit=()=>{form.events.submit({preventDefault(){}});return work.at(-1);};
  const choose=()=>{file.files=[{name:"work.jpg",size:1000}];file.events.change();};
  return {form,file,calls,choose,submit};
}
test("upload retries keep the same idempotency key after a lost response",async()=>{
  let fail=true;const fixture=uploadFixture(async()=>{if(fail){fail=false;throw Error("offline");}return {};});fixture.choose();
  await assert.rejects(fixture.submit(),/offline/);await fixture.submit();
  assert.equal(fixture.calls.length,2);assert.equal(fixture.calls[0].headers["Idempotency-Key"],fixture.calls[1].headers["Idempotency-Key"]);
});
test("choosing another gallery photo preserves previous pages and their print order", () => {
  const {form, file} = uploadFixture(async () => ({}));
  const list = form.children.find(element => element.tagName === "ol");
  const camera = form.children.find(element => element.tagName === "input" && !element.multiple);
  for (const [input, name] of [[camera, "camera.jpg"], [file, "2.jpg"], [file, "3.png"]]) {
    input.files = [{name, size: 1024}];
    input.events.change();
  }
  const names = () => list.children.map(row => row.children[0].textContent);
  assert.deepEqual(names(), ["camera.jpg", "2.jpg", "3.png"]);
  file.files = [{name:"unexpected.pdf", size:1024}];
  file.events.change();
  assert.deepEqual(names(), ["camera.jpg", "2.jpg", "3.png"]);
});
test("a selected PDF can be replaced as a single document", () => {
  const {form, file} = uploadFixture(async () => ({}));
  for (const name of ["draft.pdf", "final.pdf"]) {
    file.files = [{name, size: 1024}];
    file.events.change();
  }
  const list = form.children.find(element => element.tagName === "ol");
  assert.deepEqual(list.children.map(row => row.children[0].textContent), ["final.pdf"]);
});
test("an in-flight upload and a delivered upload cannot be submitted twice",async()=>{
  let release;const fixture=uploadFixture(()=>new Promise(resolve=>{release=resolve;}));fixture.choose();const pending=fixture.submit();fixture.submit();
  assert.equal(fixture.calls.length,1);release({});await pending;await fixture.submit();assert.equal(fixture.calls.length,1);
});
test("failure to reload after delivery does not unlock duplicate submission",async()=>{
  const fixture=uploadFixture(async()=>({}),async()=>{throw Error("refresh failed");});fixture.choose();await assert.rejects(fixture.submit(),/refresh failed/);
  await assert.rejects(fixture.submit(),/refresh failed/);assert.equal(fixture.calls.length,1);
});
