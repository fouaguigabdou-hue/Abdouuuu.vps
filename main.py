import os, json, sqlite3, shutil, subprocess, uuid, zipfile, re
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse

BASE=Path(__file__).resolve().parent
DATA=BASE/'data'; PROJECTS=DATA/'projects'; SITES=DATA/'sites'
DB=DATA/'panel.db'; TOKEN=os.getenv('PANEL_TOKEN','change-me')
DATA.mkdir(exist_ok=True); PROJECTS.mkdir(exist_ok=True); SITES.mkdir(exist_ok=True)
app=FastAPI(title='ABDOUUU TEAM VPS')

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
with db() as c:
    c.execute('''CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,name TEXT UNIQUE,type TEXT,entry TEXT,port INTEGER,container TEXT,status TEXT DEFAULT 'stopped',created TEXT DEFAULT CURRENT_TIMESTAMP)''')

def auth(x_panel_token: str|None):
    if TOKEN=='change-me':
        raise HTTPException(500,'Set PANEL_TOKEN before starting the panel')
    if x_panel_token!=TOKEN: raise HTTPException(401,'Invalid panel token')

PROCS={}; LOGS={}

def log_path(pid):
    return PROJECTS/pid/'runtime.log'

def spawn_bot(pid, root, kind, entry):
    import sys
    if pid in PROCS and PROCS[pid].poll() is None:
        return PROCS[pid]
    lp=log_path(pid); lp.parent.mkdir(parents=True, exist_ok=True)
    logf=lp.open('a', encoding='utf-8')
    if kind=='python':
        cmd=[sys.executable, entry]
    else:
        cmd=['npm','start'] if entry=='npm-start' else ['node',entry]
    proc=subprocess.Popen(cmd,cwd=str(root),stdout=logf,stderr=subprocess.STDOUT,start_new_session=True)
    PROCS[pid]=proc
    return proc

def stop_bot_process(pid):
    proc=PROCS.get(pid)
    if not proc: return
    if proc.poll() is None:
        proc.terminate()
        try: proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
    PROCS.pop(pid,None)

def safe_name(s): return re.sub(r'[^a-zA-Z0-9_.-]+','-',s).strip('-')[:40] or 'project'

def detect(root):
    if (root/'package.json').exists():
        try:
            p=json.loads((root/'package.json').read_text())
            start=p.get('scripts',{}).get('start')
            if start: return 'node', start
        except: pass
    for f in ('main.py','bot.py','app.py','index.py'):
        if (root/f).exists(): return 'python', f
    for f in ('index.js','bot.js','main.js','app.js'):
        if (root/f).exists(): return 'node', f
    return None,None

def make_dockerfile(root, kind, entry):
    if (root/'Dockerfile').exists(): return
    if kind=='python':
        (root/'Dockerfile').write_text(f'''FROM python:3.12-slim\nWORKDIR /app\nCOPY . .\nRUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi\nCMD ["python","{entry}"]\n''')
    else:
        cmd='npm start' if entry=='npm-start' else f'node {entry}'
        (root/'Dockerfile').write_text(f'''FROM node:22-alpine\nWORKDIR /app\nCOPY package*.json ./\nRUN if [ -f package.json ]; then npm install --omit=dev; fi\nCOPY . .\nCMD ["sh","-c","{cmd}"]\n''')

def rows():
    with db() as c: return [dict(x) for x in c.execute('SELECT * FROM projects ORDER BY created DESC')]

@app.get('/',response_class=HTMLResponse)
def home(): return (BASE/'static'/'index.html').read_text()

@app.get('/api/projects')
def list_projects(x_panel_token:str|None=Header(None)):
    auth(x_panel_token)
    data=rows()
    for x in data:
        if x['type']=='bot':
            proc=PROCS.get(x['id'])
            if proc and proc.poll() is None: x['status']='running'
            elif proc and proc.poll() is not None: x['status']='stopped'
    return data

@app.post('/api/upload')
async def upload(name:str=Form(...), kind:str=Form(...), file:UploadFile=File(...), x_panel_token:str|None=Header(None)):
    auth(x_panel_token)
    if kind not in ('bot','site'): raise HTTPException(400,'kind must be bot or site')
    pid=uuid.uuid4().hex[:12]; safe=safe_name(name); root=(PROJECTS if kind=='bot' else SITES)/pid; root.mkdir(parents=True)
    dest=root/file.filename
    if Path(file.filename).name!=file.filename: raise HTTPException(400,'Invalid filename')
    with dest.open('wb') as f: shutil.copyfileobj(file.file,f)
    if dest.suffix.lower()=='.zip':
        with zipfile.ZipFile(dest) as z:
            for n in z.namelist():
                p=Path(n)
                if p.is_absolute() or '..' in p.parts: raise HTTPException(400,'Unsafe zip path')
            z.extractall(root); dest.unlink()
    if kind=='site':
        index=root/'index.html'
        if not index.exists(): raise HTTPException(400,'Site must contain index.html')
        with db() as c: c.execute('INSERT INTO projects(id,name,type,entry,port,container,status) VALUES(?,?,?,?,?,?,?)',(pid,safe,'site','index.html',0,'','running'))
    else:
        k,e=detect(root)
        if not k: raise HTTPException(400,'Could not detect Python or Node entry file')
        if k=='node' and e=='npm-start': entry='npm-start'
        else: entry=e
        if k=='node' and (root/'package.json').exists():
            r=subprocess.run(['npm','install','--omit=dev'],cwd=str(root),text=True,capture_output=True)
            if r.returncode!=0: raise HTTPException(400, 'npm install failed: '+r.stderr[-2000:])
        with db() as c: c.execute('INSERT INTO projects(id,name,type,entry,port,container,status) VALUES(?,?,?,?,?,?,?)',(pid,safe,'bot',entry,0,'','stopped'))
    return {'ok':True,'id':pid}

@app.post('/api/bots/{pid}/{action}')
def bot_action(pid:str,action:str,x_panel_token:str|None=Header(None)):
    auth(x_panel_token)
    with db() as c: r=c.execute('SELECT * FROM projects WHERE id=? AND type="bot"',(pid,)).fetchone()
    if not r: raise HTTPException(404,'Bot not found')
    root=PROJECTS/pid
    if action=='start':
        try:
            proc=spawn_bot(pid,root,'python' if (root/r['entry']).suffix=='.py' else 'node',r['entry'])
        except Exception as e:
            raise HTTPException(500, str(e))
        with db() as c: c.execute('UPDATE projects SET status="running" WHERE id=?',(pid,))
    elif action=='stop':
        stop_bot_process(pid)
        with db() as c: c.execute('UPDATE projects SET status="stopped" WHERE id=?',(pid,))
    elif action=='restart':
        stop_bot_process(pid)
        try: spawn_bot(pid,root,'python' if (root/r['entry']).suffix=='.py' else 'node',r['entry'])
        except Exception as e: raise HTTPException(500,str(e))
        with db() as c: c.execute('UPDATE projects SET status="running" WHERE id=?',(pid,))
    else: raise HTTPException(400,'Unknown action')
    return {'ok':True}

@app.get('/api/bots/{pid}/logs')
def logs(pid:str,x_panel_token:str|None=Header(None)):
    auth(x_panel_token)
    with db() as c: r=c.execute('SELECT * FROM projects WHERE id=? AND type="bot"',(pid,)).fetchone()
    if not r: raise HTTPException(404,'Bot not found')
    lp=log_path(pid)
    out=lp.read_text(encoding='utf-8',errors='replace') if lp.exists() else ''
    return {'logs':out[-20000:]}

@app.on_event('startup')
def restore_running_bots():
    with db() as c: items=c.execute('SELECT * FROM projects WHERE type="bot" AND status="running"').fetchall()
    for r in items:
        root=PROJECTS/r['id']
        try: spawn_bot(r['id'],root,'python' if (root/r['entry']).suffix=='.py' else 'node',r['entry'])
        except Exception: pass

@app.get('/site/{pid}/{path:path}')
def site(pid:str,path:str=''):
    with db() as c: r=c.execute('SELECT * FROM projects WHERE id=? AND type="site"',(pid,)).fetchone()
    if not r: raise HTTPException(404,'Site not found')
    root=(SITES/pid).resolve(); target=(root/(path or 'index.html')).resolve()
    if root not in target.parents and target!=root: raise HTTPException(403,'Forbidden')
    if not target.exists() or not target.is_file(): raise HTTPException(404,'File not found')
    return FileResponse(target)
