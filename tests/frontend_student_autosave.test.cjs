"use strict";
const {test}=require('node:test');const assert=require('node:assert/strict');
const {StudentAutosave}=require('../app/frontend/student_autosave.js');
test('edits during save are serialized using the returned revision',async()=>{
  let text='first',release;const bodies=[];
  const s=new StudentAutosave({delay:60000,read:()=>({text}),send:async body=>{bodies.push(body);if(bodies.length===1)await new Promise(r=>release=r);return {revision:'r'+bodies.length};}});
  s.edit();const pending=s.flush();text='second';s.edit();release();await pending;s.dispose();
  assert.equal(bodies.length,2);assert.equal(bodies[0].text,'first');assert.equal(bodies[1].text,'second');assert.equal(bodies[1].draft_revision,'r1');assert.equal(s.dirty,false);
});
test('lost response retries identical request then sends newer changes',async()=>{
  let text='one',fail=true;const calls=[];
  const s=new StudentAutosave({delay:60000,read:()=>({text}),send:async b=>{calls.push(b);if(fail){fail=false;throw new TypeError('offline');}return {revision:'new'};}});
  s.edit();await assert.rejects(s.flush());assert.equal(s.dirty,true);text='two';s.edit();await s.flush();s.dispose();
  assert.deepEqual(calls[0],calls[1]);assert.equal(calls[2].text,'two');assert.notEqual(calls[2].request_id,calls[0].request_id);assert.equal(s.dirty,false);
});
test('conflict preserves local changes and prevents successful navigation flush',async()=>{
  const statuses=[];const s=new StudentAutosave({delay:60000,read:()=>({comment:'local'}),send:async()=>{throw new Error('draft conflict');},onStatus:status=>statuses.push(status)});
  s.edit();await assert.rejects(s.flush(),/conflict/);s.dispose();assert.equal(s.dirty,true);assert.equal(s.pending.body.comment,'local');assert.equal(statuses.at(-1),'error');
});
test('switching demo waits for student saves and does not change identity on failure',async()=>{
  const fs=require('node:fs'),vm=require('node:vm');const source=fs.readFileSync(require('node:path').join(__dirname,'../app/frontend/demo.js'),'utf8');
  const calls=[];let failure=true;
  const c=vm.createContext({state:{dirty:false},pendingSubmission:null,request:async()=>calls.push('switch'),location:{assign:()=>calls.push('navigate')},flushStudentDraft:async()=>{calls.push('save');if(failure)throw Error('offline');}});
  vm.runInContext(source.slice(source.indexOf('async function switchDemo('),source.indexOf('async function enterDemo(')),c);
  await assert.rejects(vm.runInContext('switchDemo("enter")',c));assert.deepEqual(calls,['save']);failure=false;
  await vm.runInContext('switchDemo("enter")',c);assert.deepEqual(calls,['save','save','switch','navigate']);
});
test('student notification login target is an allowed internal route',async()=>{
  const fs=require('node:fs'),vm=require('node:vm'),fields=new Map(),routes=[];
  const c=vm.createContext({URLSearchParams,location:{hash:'#token=fixture&next=student:'+ 'a'.repeat(32),pathname:'/bot-login.html',replace:value=>routes.push(value)},history:{replaceState:()=>{}},document:{getElementById:id=>{if(!fields.has(id))fields.set(id,{addEventListener:(_,f)=>fields.get(id).click=f});return fields.get(id);}},fetch:async()=>({ok:true,json:async()=>({first_name:'Ученик'})})});
  await vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../app/frontend/bot-login.js'),'utf8'),c);await fields.get('confirmLogin').click();assert.equal(routes[0],'/?open=student%3A'+'a'.repeat(32));
});
