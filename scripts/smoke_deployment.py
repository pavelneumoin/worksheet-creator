"""Run in the CI web container, exercising real separate queue worker containers."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlencode
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app/backend'))
from app import app
from utils.worksheet import demo_worksheet

token=os.environ.get('MAX_BOT_TOKEN','')
if token!='ci-only-token':
    raise SystemExit('This diagnostic is restricted to the isolated CI deployment.')
data={'auth_date':str(int(time.time())),'query_id':'ci-smoke','user':json.dumps({'id':987654321,'first_name':'CI teacher'})}
key=hmac.new(b'WebAppData',token.encode(),hashlib.sha256).digest()
data['hash']=hmac.new(key,'\n'.join(f'{k}={data[k]}' for k in sorted(data)).encode(),hashlib.sha256).hexdigest()
client=app.test_client()
def call(method,path,**kwargs):
    response=getattr(client,method)(path,base_url='https://listok.test',**kwargs)
    assert response.status_code<400,(path,response.status_code,response.json)
    return response

auth=call('post','/api/v2/auth/max',json={'init_data':urlencode(data)}).json
client.environ_base['HTTP_X_CSRF_TOKEN']=auth['csrf_token']
# The second invocation follows a web-container restart and reads the first one's class.
for saved_class in call('get','/api/v2/classes').json['classes']:
    previous=call('get','/api/v2/classes/'+saved_class['id']).json['classroom']
    assert previous['student_count']==3 and len(previous['assignments'])==1
    previous_work=call('get','/api/v2/assignments/'+previous['assignments'][0]['id']).json['assignment']
    assert previous_work['student_count']==2
    response=call('get',previous_work['result']['pdf_url']); response.close()
sheet=demo_worksheet('physics')
material=call('post','/api/v2/materials',json={'worksheet':sheet,'source':'manual_demo'}).json['material']
payload={'worksheet':sheet,'material_id':material['id'],'revision':material['revision'],'reviewed':True}
headers={'Idempotency-Key':uuid.uuid4().hex}
job=call('post','/api/v2/jobs/compile',json=payload,headers=headers).json['job']
assert call('post','/api/v2/jobs/compile',json=payload,headers=headers).json['job']['id']==job['id']
deadline=time.monotonic()+150
while job['status'] in ('queued','running') and time.monotonic()<deadline:
    time.sleep(1)
    job=call('get','/api/v2/jobs/'+job['id']).json['job']
assert job['status']=='succeeded',job
for key in ('pdf_url','keys_url','tex_url','marp_url'):
    response=call('get',job['result'][key])
    assert len(response.data)>20
    response.close()
assert call('get','/api/v2/materials/'+material['id']).json['material']['result']['artifact_id']==job['result']['artifact_id']
classroom=call('post','/api/v2/classes',json={'name':'CI '+material['id'][:12]}).json['classroom']
base='/api/v2/classes/'+classroom['id']
classroom=call('post',base+'/students',json={'revision':classroom['revision'],'names':['Demo pupil 1','Demo pupil 2']}).json['classroom']
assignment_payload={'revision':classroom['revision'],'edition_id':job['result']['artifact_id'],
                    'title':'CI fixed worksheet','due_date':'2026-11-06','request_key':uuid.uuid4().hex}
assignment=call('post',base+'/assignments',json=assignment_payload).json['assignment']
assert assignment['worksheet']==sheet and assignment['student_count']==2
classroom=call('get',base).json['classroom']
call('post',base+'/students',json={'revision':classroom['revision'],'names':['Later pupil']})
assert call('post',base+'/assignments',json=assignment_payload).json['assignment']['id']==assignment['id']
assert call('get','/api/v2/assignments/'+assignment['id']).json['assignment']['student_count']==2
print('PASS: signed MAX fixture, CSRF, separate compiler, four downloads, classes, fixed roster, retry and restart persistence')
