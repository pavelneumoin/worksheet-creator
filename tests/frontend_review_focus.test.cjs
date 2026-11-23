const test = require('node:test');
const assert = require('node:assert/strict');
const {reviewNeedsAttention,reviewAttentionIndices,reviewBox,reviewScoreLabel} = require('../app/frontend/review_focus.js');
const exact = {state:'readable',comparison:'matches',score:1};
test('attention includes unclear, blank, manual and ungraded even when marked checked',()=>{
  for(const answer of [{...exact,state:'unclear'},{...exact,state:'blank'},{...exact,comparison:'manual'},{...exact,score:null},{...exact,checked:true,score:null}]) assert.equal(reviewNeedsAttention(answer),true);
  assert.equal(reviewNeedsAttention(exact),false);
});
test('partial or edited answer requires attention until the teacher marks it checked',()=>{
  for(const score of [0,.25,.5,.75]) {
    assert.equal(reviewNeedsAttention({...exact,score}),true);
    assert.equal(reviewNeedsAttention({...exact,score,checked:true}),false);
  }
  assert.equal(reviewNeedsAttention({...exact,teacher_edited:true}),true);
});
test('malformed OCR bounds cannot position an arbitrary image region',()=>{
  for(const box of [null,[0,0,1],[0,0,Infinity,1],[false,0,1,1],[-1,0,1,1],[20,10,5,4]]) assert.equal(reviewBox(box),null);
  assert.deepEqual(reviewBox([0,0,1000,1000]),[0,0,1000,1000]);
});
test('correcting a partial score keeps the current question in the picker until confirmed', () => {
  const answers = [exact, {...exact, score: 0.5}, {...exact, state: 'unclear'}];
  assert.deepEqual(reviewAttentionIndices(answers), [1, 2]);
  answers[1].score = 1;
  assert.deepEqual(reviewAttentionIndices(answers, 1), [1, 2]);
  assert.deepEqual(reviewAttentionIndices(answers), [2]);
  answers[1].checked = true;
  assert.deepEqual(reviewAttentionIndices(answers, 1), [2]);
});
test('quarter scores retain precision and Russian decimal comma',()=>{
  assert.equal(reviewScoreLabel(.25),'0,25'); assert.equal(reviewScoreLabel(.5),'0,5');
  assert.equal(reviewScoreLabel(0),'0'); assert.equal(reviewScoreLabel(null),'Не оценено');
});
