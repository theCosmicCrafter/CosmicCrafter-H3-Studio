"""Dependency-free H3 Timeline v1 client. Downloaded instructions remain data."""
import argparse
import hashlib
import http.client
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

PREFIX = '/h3c/api/v1'
MAX_JSON = 32 * 1024 * 1024


class ClientError(ValueError):
    def __init__(self, message, *, status=None, code=None):
        super().__init__(message)
        self.status, self.code = status, code


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ClientError('HTTP redirect refused; use the configured serving origin.')


def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')


def atomic_json(path, value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(encoded(value)); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally: temporary.unlink(missing_ok=True)


class Client:
    def __init__(self, base_url, *, timeout=30):
        parts=urllib.parse.urlsplit(base_url)
        if (parts.scheme not in ('http','https') or not parts.hostname or parts.username or parts.password
                or parts.query or parts.fragment or '\\' in base_url):
            raise ClientError('Use an HTTP serving base URL with an optional reverse-proxy prefix.')
        if not math.isfinite(timeout) or timeout <= 0: raise ClientError('Timeout must be positive and finite.')
        self.base_url, self.timeout = base_url.rstrip('/'), timeout
        self.opener = urllib.request.build_opener(NoRedirect())

    def _url(self, path):
        parts=urllib.parse.urlsplit(path)
        decoded=urllib.parse.unquote(parts.path)
        if (parts.scheme or parts.netloc or parts.fragment or not path.startswith('/') or path.startswith('//')
                or '\\' in decoded or any(part in ('.','..') for part in decoded.split('/'))):
            raise ClientError('Resource URL must be a same-origin relative path.')
        return self.base_url+path

    def request(self, path, *, method='GET', body=None, key=None, timeout=None, headers=None):
        request_headers={'Accept':'application/json',**(headers or {})}
        if key is not None: request_headers['Idempotency-Key']=key
        data=encoded(body) if isinstance(body,dict) else body
        if isinstance(body,dict): request_headers['Content-Type']='application/json'
        request=urllib.request.Request(self._url(path),data=data,headers=request_headers,method=method)
        status=200
        try:
            try: response=self.opener.open(request,timeout=self.timeout if timeout is None else timeout)
            except urllib.error.HTTPError as error: response=error; status=error.code
            with response: raw=response.read(MAX_JSON+1)
        except ClientError: raise
        except (OSError,http.client.HTTPException,urllib.error.URLError) as error:
            raise ClientError(f'Connection failed; preserve the request key and job ID: {error}') from error
        if len(raw)>MAX_JSON: raise ClientError('JSON response exceeds the client limit.')
        try:
            result=json.loads(raw,parse_constant=lambda value:(_ for _ in ()).throw(ValueError(value)))
            if not isinstance(result,dict): raise ValueError()
        except (ValueError,UnicodeError): raise ClientError('Server returned invalid or truncated JSON.',status=status) from None
        if status>=400:
            detail=result.get('error',{})
            raise ClientError(detail.get('message',f'HTTP {status}'),status=status,code=detail.get('code'))
        return result

    def _project(self, identifier, suffix=''): return PREFIX+'/projects/'+urllib.parse.quote(identifier,safe='')+suffix
    def capabilities(self): return self.request(PREFIX+'/capabilities')
    def create(self, body, key): return self.request(PREFIX+'/projects',method='POST',body=body,key=key)
    def get(self, project_id): return self.request(self._project(project_id))
    def update(self, project_id, body): return self.request(self._project(project_id),method='PUT',body=body)
    def plan(self, project_id, body): return self.request(self._project(project_id,'/plan'),method='POST',body=body)
    def render(self, project_id, body, key): return self.request(self._project(project_id,'/jobs'),method='POST',body=body,key=key)
    def job(self, job_id): return self.request(PREFIX+'/jobs/'+urllib.parse.quote(job_id,safe=''))
    def resume(self, job_id): return self.request(PREFIX+'/jobs/'+urllib.parse.quote(job_id,safe='')+'/resume',method='POST',body={})
    def cancel(self, job_id): return self.request(PREFIX+'/jobs/'+urllib.parse.quote(job_id,safe='')+'/cancel',method='POST',body={})
    def abandon(self, job_id, reason, confirm_prompt_id):
        return self.request(PREFIX+'/jobs/'+urllib.parse.quote(job_id,safe='')+'/abandon',method='POST',
                            body={'reason':reason,'confirm_prompt_id':confirm_prompt_id})
    def takes(self, project_id, box_id): return self.request(self._project(project_id,'/takes?'+urllib.parse.urlencode({'box':box_id})))
    def use_take(self, project_id, body): return self.request(self._project(project_id,'/takes/use'),method='POST',body=body)
    def export(self, project_id, mode='fork'): return self.request(self._project(project_id,'/workflow?'+urllib.parse.urlencode({'mode':mode})))

    def upload(self, path, kind):
        path=Path(path); checksum=hashlib.sha256()
        with path.open('rb') as stream:
            while chunk:=stream.read(1024*1024): checksum.update(chunk)
        boundary='h3c'+uuid.uuid4().hex
        prefix=(f'--{boundary}\r\nContent-Disposition: form-data; name="kind"\r\n\r\n{kind}\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="expected_sha256"\r\n\r\n{checksum.hexdigest()}\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="source"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()
        suffix=f'\r\n--{boundary}--\r\n'.encode()
        with path.open('rb') as stream:
            def chunks():
                yield prefix
                while chunk:=stream.read(1024*1024): yield chunk
                yield suffix
            result=self.request(PREFIX+'/assets',method='POST',body=chunks(),headers={
                'Content-Type':f'multipart/form-data; boundary={boundary}',
                'Content-Length':str(len(prefix)+os.fstat(stream.fileno()).st_size+len(suffix))})
        if result.get('sha256')!=checksum.hexdigest(): raise ClientError('Uploaded asset hash differs from the original source.')
        return result

    def wait(self, job_id, *, deadline=3600):
        if not math.isfinite(deadline) or deadline <= 0: raise ClientError('Polling deadline reached; retain the job ID.')
        until=time.monotonic()+deadline
        job=None
        while True:
            remaining=until-time.monotonic()
            if remaining<=0:
                held=(job or {}).get('blocked_by')
                # A held job elsewhere bars admission; name it so the caller can resume or abandon it.
                suffix=f' Job is waiting behind held job {held["job_id"]} ({held.get("error_code") or held.get("state")}).' if held else ''
                raise ClientError('Polling deadline reached; retain the job ID.'+suffix,code='blocked' if held else None)
            job=self.request(PREFIX+'/jobs/'+urllib.parse.quote(job_id,safe=''),timeout=min(self.timeout,remaining))
            if job.get('state')=='succeeded': return job
            if job.get('state') in ('failed','needs_reconciliation'):
                raise ClientError(f'Job {job_id} {job["state"]}: {(job.get("error") or {}).get("message", "inspect its status")}',code=job['state'])
            time.sleep(min(1,max(0,until-time.monotonic())))

    def download(self, artifact, destination):
        checksum=artifact.get('sha256'); size=artifact.get('size')
        if not isinstance(checksum,str) or not re.fullmatch('[a-f0-9]{64}',checksum) or type(size) is not int or size<=0:
            raise ClientError('Artifact needs a valid hash and byte size.')
        url=self._url(artifact.get('download_url',''))
        destination=Path(destination); destination.parent.mkdir(parents=True,exist_ok=True)
        temporary=destination.with_name(destination.name+'.'+uuid.uuid4().hex+'.tmp')
        hasher=hashlib.sha256(); count=0
        try:
            with self.opener.open(url,timeout=self.timeout) as response,temporary.open('xb') as stream:
                while chunk:=response.read(1024*1024):
                    count+=len(chunk)
                    if count>size: raise ClientError('Artifact byte size differs from metadata.')
                    hasher.update(chunk); stream.write(chunk)
                if hasher.hexdigest()!=checksum: raise ClientError('Artifact hash mismatch.')
                if count!=size: raise ClientError('Artifact byte size differs from metadata.')
                stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary,destination); return destination
        except (OSError,http.client.HTTPException,urllib.error.URLError) as error:
            raise ClientError(f'Artifact download failed: {error}') from error
        finally: temporary.unlink(missing_ok=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',required=True)
    parser.add_argument('operation',choices=['capabilities','upload','create','get','update','plan','render','status','resume','cancel','abandon','takes','use-take','download','export'])
    for name in ('project','job','box','body','receipt','key','file','kind','destination','reason','prompt'): parser.add_argument('--'+name)
    parser.add_argument('--mode',choices=['fork','attached'],default='fork')
    parser.add_argument('--wait',action='store_true'); parser.add_argument('--deadline',type=float,default=3600)
    args=parser.parse_args(argv); client=Client(args.base_url)
    body=json.loads(Path(args.body).read_text(encoding='utf-8')) if args.body else None
    def required(name):
        value=getattr(args,name)
        if not value: parser.error('--'+name+' is required for '+args.operation)
        return value
    operation=args.operation
    if operation in ('create','render'):
        path=Path(required('receipt')); required('body')
        identity={'base_url':client.base_url,'operation':operation,'project_id':required('project') if operation=='render' else None,'request':body}
        if path.exists():
            receipt=json.loads(path.read_text(encoding='utf-8'))
            if any(receipt.get(key)!=value for key,value in identity.items()): raise ClientError('Receipt request identity differs; use the original request.')
            if args.key and receipt['key']!=args.key: raise ClientError('Receipt key differs.')
        else:
            receipt={**identity,'key':args.key or str(uuid.uuid4())}; path.parent.mkdir(parents=True,exist_ok=True)
            try:
                with path.open('xb') as stream:
                    stream.write(encoded(receipt)); stream.flush(); os.fsync(stream.fileno())
            except FileExistsError: raise ClientError('Receipt was created concurrently; retry its original request.') from None
        result=receipt.get('response')
        if result is None:
            result=client.create(body,receipt['key']) if operation=='create' else client.render(args.project,body,receipt['key'])
            receipt['response']=result; atomic_json(path,receipt)
        if operation=='render' and args.wait: result=client.wait(result['id'],deadline=args.deadline)
    elif operation=='capabilities': result=client.capabilities()
    elif operation=='upload': result=client.upload(Path(required('file')),required('kind'))
    elif operation=='get': result=client.get(required('project'))
    elif operation in ('update','plan','use-take'):
        required('body'); result=getattr(client,operation.replace('-','_'))(required('project'),body)
    elif operation in ('status','resume'): result=getattr(client,'job' if operation=='status' else 'resume')(required('job'))
    elif operation=='cancel': result=client.cancel(required('job'))
    elif operation=='abandon': result=client.abandon(required('job'),required('reason'),args.prompt)
    elif operation=='takes': result=client.takes(required('project'),required('box'))
    elif operation=='export': result=client.export(required('project'),args.mode)
    else:
        required('body'); result={'path':str(client.download(body,Path(required('destination'))))}
    if args.destination and operation!='download': atomic_json(args.destination,result)
    print(encoded(result).decode('utf-8')); return result


if __name__=='__main__':
    try: main()
    except (ClientError,OSError,ValueError) as error: raise SystemExit(str(error))
