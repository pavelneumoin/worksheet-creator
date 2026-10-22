"""Opt-in LOCAL API smoke test: five GigaChat calls, plus possible variant retries."""
import argparse
import json
from pathlib import Path
import time
import uuid
import requests


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true')
    args=parser.parse_args()
    if not args.run:
        parser.error('Use --run to make real provider requests')
    root=Path(__file__).resolve().parents[1]
    base='http://127.0.0.1:3005'
    session=requests.Session()
    session.trust_env=False  # Loopback only; never forwarded through a proxy.
    auth=session.post(base+'/api/v2/auth/local',timeout=10);auth.raise_for_status()
    session.headers['X-CSRF-Token']=auth.json()['csrf_token']
    sheet=session.get(base+'/api/v2/demo',timeout=10).json()['worksheet']
    material=session.post(base+'/api/v2/materials',json={'worksheet':sheet,'source':'manual_demo'},timeout=10).json()['material']
    def finish(response):
        response.raise_for_status()
        job=response.json()['job']
        deadline=time.monotonic()+1500
        while job['status'] in ('queued','running') and time.monotonic()<deadline:
            time.sleep(2)
            response=session.get(base+'/api/v2/jobs/'+job['id'],timeout=10)
            response.raise_for_status();job=response.json()['job']
        if job['status']!='succeeded':
            return {'error':job.get('error') or 'Queue timeout','job':job}
        response=session.get(base+'/api/v2/materials/'+job['result']['material_id'],timeout=10)
        response.raise_for_status()
        return response.json()['material']
    report=[]
    for level in ('same','easier','harder'):
        start=time.monotonic()
        response=session.post(base+'/api/v2/jobs/variant',headers={'Idempotency-Key':uuid.uuid4().hex},
                              json={'worksheet':sheet,'difficulty':level,'material_id':material['id'],'revision':material['revision']},timeout=15)
        result=finish(response)
        report.append({'case':level,'http_status':200 if 'worksheet' in result else 500,'seconds':round(time.monotonic()-start,2),'result':result})
        print(level,response.status_code,flush=True)
    photo=root/'docs/examples/math-source.png'
    with photo.open('rb') as first,photo.open('rb') as second:
        response=session.post(base+'/api/v2/jobs/recognize',headers={'Idempotency-Key':uuid.uuid4().hex},files=[('files',('page1.png',first,'image/png')),('files',('page2.png',second,'image/png'))],data={'subject':'math'},timeout=30)
    result=finish(response)
    report.append({'case':'two_pages_same_photo','http_status':200 if 'worksheet' in result else 500,'result':result})
    print('two pages','tasks',len(result.get('worksheet',{}).get('tasks',[])),flush=True)
    path=root/'output/qa/live-workflows.json';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    session.post(base+'/api/v2/auth/logout',timeout=10)
    print('Report:',path)
    failed=any(row['http_status']!=200 for row in report)
    failed=failed or len(report[-1]['result'].get('worksheet',{}).get('tasks',[]))!=6
    raise SystemExit(1 if failed else 0)


if __name__=='__main__':main()
