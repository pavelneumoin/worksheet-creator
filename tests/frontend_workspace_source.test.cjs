"use strict";
const {test}=require("node:test"),assert=require("node:assert/strict");
const fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const source=fs.readFileSync(path.join(__dirname,"../app/frontend/script.js"),"utf8");
const context=vm.createContext({});
vm.runInContext(source.slice(source.indexOf("function appendWorksheetSource("),source.indexOf('$("recognizeBtn").addEventListener("click"')),context);
function payload(files,text,mode){const entries=[];context.appendWorksheetSource({append:(key,value)=>entries.push([key,value])},files,text,mode);return entries;}

test("text mode excludes previously selected files without clearing them",()=>{
  const file={name:"previous.pdf"},files=[file],text="Решите $x^2=4$.";
  assert.deepEqual(payload(files,text,"text"),[["text",text]]);
  assert.deepEqual(files,[file]);
});
test("file mode excludes stored text and preserves the order of photos",()=>{
  const files=[{name:"first.jpg"},{name:"second.jpg"}],text="Старое условие";
  assert.deepEqual(payload(files,text,"files"),[["files",files[0]],["files",files[1]]]);
  assert.deepEqual(payload(files,text,"text"),[["text",text]]);
});
test("empty selected source does not silently fall back to hidden input",()=>{
  assert.deepEqual(payload([],"Hidden text","files"),[]);
  assert.deepEqual(payload([{name:"hidden.pdf"}],"","text"),[["text",""]]);
});
test("pages without the new source selector keep the existing combined payload",()=>{
  const files=[{name:"page.png"}],text="Дополнение к фотографии";
  assert.deepEqual(payload(files,text,undefined),[["files",files[0]],["text",text]]);
});
