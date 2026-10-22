// Actual Marp parser checks: layout, formula rendering, and escaped untrusted prose.
const { Marp } = require('@marp-team/marp-core');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const root = path.resolve(__dirname, '..');
const python = process.env.LISTOK_PYTHON || (process.platform === 'win32' ? path.join(root,'.venv/Scripts/python.exe') : 'python');
if (!process.env.LISTOK_SKIP_MARP_SAMPLES) execFileSync(python, [path.join(__dirname, 'prepare_marp_samples.py')], {cwd:root, stdio:'inherit'});
const output = path.join(root, 'output/qa/marp');
for (const name of ['math_1_3_grid','physics_1_3_grid','math_2_2_blank','math_2_6_none']) {
  for (const type of ['worksheet','answers']) {
    const directory=path.join(output,name);
    const marp=new Marp({html:true,math:'katex'});
    marp.themeSet.add(fs.readFileSync(path.join(directory,'listok.css'),'utf8'));
    const source=fs.readFileSync(path.join(directory,type+'.md'),'utf8');
    const result=marp.render(source);
    const expected=type==='worksheet' && name==='math_2_2_blank' ? 2 : 1;
    assert.equal((result.html.match(/<section\b/g)||[]).length,expected,name);
    assert.match(result.html,/katex/);
    assert.match(result.css,/297mm/);
    assert.doesNotMatch(result.html,/katex-error/);
    assert.equal((result.html.match(/class="task"/g)||[]).length,3);
    // A malicious title/condition must stay inert after real Markdown rendering.
    const hostile=source.replace('# ', '# \\<script\\>alert\\(1\\)\\<\\/script\\> \\!\\[img\\]\\(https\\:\\/\\/evil.test\\) ');
    const escaped=marp.render(hostile).html;
    assert(!/<script>alert|<img[^>]*evil\.test/.test(escaped), 'Untrusted HTML was interpreted');
    assert.equal((escaped.match(/<script\b/g)||[]).length, (result.html.match(/<script\b/g)||[]).length);
    fs.writeFileSync(path.join(directory,type+'.html'),'<!doctype html><html lang="ru"><meta charset="utf-8"><style>'+result.css+'</style><body>'+result.html+'</body></html>');
  }
}
console.log('PASS: 8 Marp documents, A4, pagination, math, tasks, escaped HTML/links');
