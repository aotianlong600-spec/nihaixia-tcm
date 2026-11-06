import asyncio
import json
import socket
import ssl
from urllib.request import build_opener, HTTPSHandler, ProxyHandler

import uvicorn
from app.main import create_app
from app.lan import ensure_tls
from scripts.run import serve


def test_private_node_precedes_global_path_only_when_installed(tmp_path,monkeypatch):
    from scripts.run import configure_node_path
    import os
    monkeypatch.setenv('PATH','synthetic-global-path')
    configure_node_path(tmp_path)
    assert os.environ['PATH']=='synthetic-global-path'
    runtime=tmp_path/'.runtime'/'node';runtime.mkdir(parents=True)
    (runtime/'node.exe').write_bytes(b'synthetic-binary')
    configure_node_path(tmp_path)
    assert os.environ['PATH']==str(runtime)+os.pathsep+'synthetic-global-path'


def test_local_and_tls_listeners_share_one_app_and_shutdown(tmp_path, monkeypatch):
    app=create_app(tmp_path)
    tls=ensure_tls(tmp_path,['192.168.50.20'])
    config=uvicorn.Config
    servers=[]
    original_serve=uvicorn.Server.serve
    def configuration(*args,**kwargs):
        kwargs['host']='127.0.0.1';kwargs['port']=0
        return config(*args,**kwargs)
    async def track(server,*args,**kwargs):
        servers.append(server)
        return await original_serve(server,*args,**kwargs)
    monkeypatch.setattr(uvicorn,'Config',configuration)
    monkeypatch.setattr(uvicorn.Server,'serve',track)
    context=ssl.create_default_context(cafile=tls['ca_cert'])
    opener=build_opener(ProxyHandler({}),HTTPSHandler(context=context))
    def status(url):
        with opener.open(url+'/api/status',timeout=3) as response: return json.load(response)
    async def exercise():
        runner=asyncio.create_task(serve(app,tls))
        try:
            for _ in range(200):
                if len(servers)==2 and all(s.started for s in servers):break
                await asyncio.sleep(.01)
            assert len(servers)==2 and all(s.started for s in servers)
            assert all(s.config.app is app for s in servers)
            ports=[s.servers[0].sockets[0].getsockname()[1] for s in servers]
            local=await asyncio.to_thread(status,f'http://127.0.0.1:{ports[0]}')
            phone=await asyncio.to_thread(status,f'https://127.0.0.1:{ports[1]}')
            assert local==phone and local['version']=='0.4.1'
            servers[0].should_exit=True
            await asyncio.wait_for(runner,5)
            assert all(s.should_exit for s in servers)
        finally:
            if not runner.done():runner.cancel()
            await asyncio.gather(runner,return_exceptions=True)
    asyncio.run(exercise())
