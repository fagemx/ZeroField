"""SPEC16 namespace transport, including bounded raw imports and private binary output."""
from __future__ import annotations
import hashlib
import re
from urllib.parse import parse_qs
from project_docs import writing_store as store, writing_service as service, story_openapi as story

ROUTE=re.compile(r'^/episodes/([A-Za-z0-9_-]+)/writing(?:/(.*))?$')
HEADER_NAMES=('Idempotency-Key','Content-Type','X-File-Name','X-File-Purpose')


class BinaryResponse:
    def __init__(self, body: bytes, content_type: str, *, status=200, headers=None):
        if not isinstance(body,bytes): raise TypeError('Binary response requires bytes.')
        self.body,self.content_type,self.status,self.headers=body,content_type,status,dict(headers or {})


def dispatch(conn, scope, method, tail, body, query, *, raw=None, headers=None):
    return service.dispatch(conn,scope,method,tail,body,query,raw=raw,headers=headers)


def handle(handler, parsed, method, me):
    """Called before ALL legacy write/idempotency gates; old paths remain unchanged."""
    from project_docs import http
    path=parsed.path[len(story.BASE):]
    match=ROUTE.fullmatch(path)
    if not match: return False
    conn=None
    try:
        tail=match[2] or 'workspace'
        readonly=method=='GET' or (method=='POST' and tail in ('search','compare','exports'))
        if method not in ('GET','POST','PUT','PATCH'): raise story.StoryError(400,'DRAMA_REQUEST_FAILED','Unsupported writing method.')
        if method!='GET' and not handler.headers.get('Authorization','').startswith('Bearer '):
            refused=http._write_allowed(handler)
            if refused: raise story.StoryError(403,'DRAMA_OPERATION_NOT_ALLOWED',refused)
        conn=http.open_connection();http._ensure_schema(conn)
        credential=hashlib.sha256(handler.headers.get('Authorization','cookie').encode()).hexdigest()
        scope=store.scope_for(conn,me,match[1],write=not readonly,credential_scope=credential)
        headers={name:handler.headers[name] for name in HEADER_NAMES if handler.headers.get(name) is not None}
        body={};raw=None
        if method in ('POST','PUT','PATCH'):
            if method=='POST' and tail=='imports':
                try: length=int(handler.headers.get('Content-Length','0'))
                except ValueError: story.invalid('Invalid upload length.')
                if not 0<=length<=8*1024*1024: store.fail('LIMIT_EXCEEDED','Writing imports support up to 8 MiB.',413)
                raw=handler.rfile.read(length);handler._body_consumed=True
                if len(raw)!=length: story.invalid('Incomplete writing upload.')
            else:
                body,error=http._json_body(handler)
                if error: raise story.StoryError(error[0],'DRAMA_VALIDATION_FAILED',error[1]['error'])
        query={k:v[0] for k,v in parse_qs(parsed.query).items()}
        result=dispatch(conn,scope,method,tail,body,query,raw=raw,headers=headers)
        conn.commit()
        if isinstance(result,BinaryResponse):
            extra={k:v for k,v in result.headers.items() if k.lower() in ('content-security-policy','x-frame-options') and '\r' not in str(v) and '\n' not in str(v)}
            if result.content_type.startswith('text/html'):
                extra['Content-Security-Policy']="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
            disposition=result.headers.get('Content-Disposition')
            if disposition: disposition=re.sub(r'[\r\n\x00-\x1f\x7f/\\]','_',str(disposition))[:240]
            handler.send_skillops_bytes(result.status,result.content_type,result.body,cache_control='private, no-store',disposition=disposition,extra_headers=extra)
        else:
            handler.send_json(200,{'code':0,'msg':'success','errorMessages':None,'data':result})
    except Exception as exc:
        if conn: conn.rollback()
        if isinstance(exc,story.StoryError): status,code,message=exc.status,exc.code,str(exc)
        elif isinstance(exc,(ValueError,TypeError,KeyError)): status,code,message=422,'DRAMA_VALIDATION_FAILED','Invalid writing request.'
        else: status,code,message=500,'DRAMA_REQUEST_FAILED','Writing service unavailable; check server deployment.'
        import uuid
        payload={'code':code,'message':message,'requestId':'req_'+uuid.uuid4().hex[:16]}
        if isinstance(exc,story.StoryError) and exc.details is not None: payload['details']=exc.details
        handler.send_json(status,payload)
    finally:
        if conn: conn.close()
    return True
