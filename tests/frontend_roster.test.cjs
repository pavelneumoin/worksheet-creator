const test = require('node:test');
const assert = require('node:assert/strict');
const {rosterNames,rosterCsv,rosterMapping} = require('../app/frontend/roster_import.js');

test('roster preserves duplicate names and strips list numbering, not initials',()=>{
  assert.deepEqual(rosterNames('1. Иванов Иван\r\n2) Иванов Иван\n\nА. С. Петров'),['Иванов Иван','Иванов Иван','А. С. Петров']);
});
test('CSV preserves Cyrillic, BOM, quotes and guards spreadsheet formulas',()=>{
  const csv=rosterCsv([['У-AB','Иванов "Иван"'],['У-CD','=HYPERLINK("bad")'],['У-EF','  +SUM(1;2)']]);
  assert.ok(csv.startsWith('\uFEFF"Код ученика";"ФИО"\r\n'));
  assert.ok(csv.includes('"Иванов ""Иван"""'));
  assert.ok(csv.includes('"\'=HYPERLINK'));
  assert.ok(csv.includes('"\'  +SUM'));
});
test('name mapping follows committed import order rather than sorted class list',()=>{
  assert.deepEqual(rosterMapping([{code:'У-Z'},{code:'У-A'}],['Первый','Второй']),[['У-Z','Первый'],['У-A','Второй']]);
  assert.throws(()=>rosterMapping([{code:'У-A'}],['Первый','Второй']));
  assert.throws(()=>rosterMapping([{code:'У-A'},{code:'У-A'}],['Первый','Второй']));
});
