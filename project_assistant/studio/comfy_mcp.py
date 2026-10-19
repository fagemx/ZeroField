"""Official Cloud MCP capability discovery only; no tools/call or subprocess bridge.

Comfy documents Streamable HTTP + X-API-Key. MCP 2025-06-18 defines the
initialize/initialized/tools-list lifecycle. Discovery is never execution consent.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from . import runtime, model_router
from .comfy_router import _NoRedirect


def configuration_status():
    url=os.environ.get('COMFY_MCP_URL','').strip() or 'https://cloud.comfy.org/mcp'
    try:
        model_router._endpoint(url)
        parts=urlsplit(url)
        if parts.path!='/mcp' or parts.query:
            raise runtime.WorkerError('Comfy MCP requires the configured /mcp endpoint without query credentials.')
    except runtime.WorkerError:
        return {'configured':False,'connection_state':'not_checked','generation_enabled':False}
    allowed='COMFY_API_KEY' in {v.strip() for v in os.environ.get('OPENBENCH_AGENT_KEY_ENVS','').split(',')}
    return {'configured':bool(os.environ.get('COMFY_API_KEY')) and allowed,'connection_state':'not_checked',
            'credential_reference':'COMFY_API_KEY','credential_allowlisted':allowed,'transport':'streamable_http',
            'protocol_version':'2025-06-18','generation_enabled':False,'local_stdio_state':'not_started'}


def discover(ctx, card):
    """Authenticated read-only capability handshake; caller must be writable crew.

    Never returns server instructions/descriptions, key, session ID or raw errors.
    No OAuth login, CLI launch, tools/call, model submission or Judge debit occurs.
    """
    from project_assistant import execution_governance as governance
    if card['engine_config']['driver']!='comfy_router' or not configuration_status()['configured']:
        raise runtime.WorkerError('Configure the official Comfy MCP connection first.')
    url=os.environ.get('COMFY_MCP_URL','').strip() or 'https://cloud.comfy.org/mcp'
    deadline=time.monotonic()+15
    session=None
    version=None
    def request(body=None, method='POST'):
        def check(conn):
            governance.live(conn,ctx,destination=url)
            governance.media_credentials(conn,ctx,card)
        governance.transaction(ctx,check)
        left=min(governance.remaining(ctx,15),deadline-time.monotonic())
        if left<=0:
            raise runtime.WorkerError('Comfy MCP discovery timed out.')
        headers={'X-API-Key':runtime.configured_token({'api_key_env':'COMFY_API_KEY'}),
                 'Accept':'application/json, text/event-stream','Content-Type':'application/json'}
        if session:headers['Mcp-Session-Id']=session
        if version:headers['MCP-Protocol-Version']=version
        raw=json.dumps(body).encode() if body is not None else None
        req=urllib.request.Request(url,data=raw,headers=headers,method=method)
        try:
            with urllib.request.build_opener(_NoRedirect).open(req,timeout=left) as response:
                received=response.headers.get('Mcp-Session-Id')
                if response.status in (202,204):return None,received
                if response.headers.get_content_type()=='text/event-stream':
                    total=0;data=[];pending=b''
                    while True:
                        chunk=response.read1(4096)
                        total+=len(chunk)
                        if total>131072 or time.monotonic()>=deadline:
                            raise runtime.WorkerError('Comfy MCP discovery exceeded transport bounds.')
                        governance.transaction(ctx,check)
                        if not chunk:break
                        pending+=chunk
                        while b'\n' in pending:
                            line,pending=pending.split(b'\n',1)
                            if line.strip()==b'' and data:
                                value=json.loads(b'\n'.join(data));data=[]
                                if isinstance(value,dict) and value.get('id')==body.get('id'):return value,received
                            elif line.startswith(b'data:'):data.append(line[5:].strip())
                    raise runtime.WorkerError('Comfy MCP ended without a discovery response.')
                chunks=[];total=0
                while True:
                    chunk=response.read1(4096)
                    total+=len(chunk)
                    governance.transaction(ctx,check)
                    if total>131072 or time.monotonic()>=deadline:
                        raise runtime.WorkerError('Comfy MCP discovery exceeded transport bounds.')
                    if not chunk:break
                    chunks.append(chunk)
                value=json.loads(b''.join(chunks))
                governance.transaction(ctx,check)
                return value,received
        except (urllib.error.URLError,TimeoutError,OSError,ValueError):
            raise runtime.WorkerError('Comfy MCP discovery unavailable; no generation was requested.') from None
    try:
        response,session=request({'jsonrpc':'2.0','id':1,'method':'initialize','params':{
            'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'ZeroField-discovery','version':'1.0'}}})
        if session is not None and (len(session)>256 or not re.fullmatch(r'[\x21-\x7e]+',session)):
            raise runtime.WorkerError('Invalid Comfy MCP session header.')
        result=response.get('result',{}) if isinstance(response,dict) and response.get('jsonrpc')=='2.0' and response.get('id')==1 else {}
        if not isinstance(result,dict):
            raise runtime.WorkerError('Invalid Comfy MCP initialization document.')
        version=result.get('protocolVersion')
        if version!='2025-06-18' or not isinstance(result.get('capabilities'),dict) or 'tools' not in result['capabilities']:
            raise runtime.WorkerError('Comfy MCP discovery protocol/capability is unsupported.')
        request({'jsonrpc':'2.0','method':'notifications/initialized'})
        response,_=request({'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}})
        result=response.get('result',{}) if isinstance(response,dict) and response.get('jsonrpc')=='2.0' and response.get('id')==2 else {}
        if not isinstance(result,dict):
            raise runtime.WorkerError('Invalid Comfy MCP discovery document.')
        tools=result.get('tools')
        if not isinstance(tools,list) or len(tools)>500:
            raise runtime.WorkerError('Invalid Comfy MCP tool discovery.')
        names=[t['name'] for t in tools if isinstance(t,dict) and isinstance(t.get('name'),str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',t['name'])]
        return {'connection_state':'reachable','transport':'streamable_http','protocol_version':version,
                'tools':names,'has_more':bool(result.get('nextCursor')),'generation_enabled':False,
                'local_stdio_state':'not_started','billing_verified':False}
    finally:
        if session and version=='2025-06-18':
            try:request(method='DELETE')
            except runtime.WorkerError:pass
