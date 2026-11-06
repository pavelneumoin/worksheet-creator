const test=require('node:test');
const assert=require('node:assert/strict');
const {nextQueueItem}=require('../app/frontend/batch_queue.js');
const a={review_id:'a',task_id:'1',resolved:true},b={review_id:'a',task_id:'2',resolved:false},c={review_id:'b',task_id:'1',resolved:false};
test('continue crosses pupil boundaries and skips resolved answers',()=>{
  assert.equal(nextQueueItem([a,b,c],b,1,true),c);
  assert.equal(nextQueueItem([a,b,c],c,1,true),b);
  assert.equal(nextQueueItem([a,b,c],null,1,true),b);
});
test('back can reopen a resolved answer; exhausted queue has no next',()=>{
  assert.equal(nextQueueItem([a,b,c],b,-1),a);
  assert.equal(nextQueueItem([a],a,1,true),null);
  assert.equal(nextQueueItem([],b,1,true),null);
});
test('deleted current item resumes from first unresolved rather than skipping it',()=>{
  assert.equal(nextQueueItem([b,c],a,1,true),b);
});
