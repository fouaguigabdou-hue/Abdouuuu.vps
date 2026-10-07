import os, json, sqlite3, shutil, subprocess, uuid, zipfile, re, signal, sys
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException
from fastapi.responses import HTMLResponse, FileResponse

BASE=Path(__file__).resolve().parent.parent
DATA=Path(os.getenv('DATA_DIR', str(BASE/'data'))); PROJECTS=DATA/'projects'; SITES=DATA/'sites'; LOGS=DATA/'logs'
DB=DATA/'panel.db'; TOKEN=os.getenv('PANEL_TOKEN','change-me')
for p in (DATA, PROJECTS, SITES, LOGS): p.mkdir(parents=True, exist_ok=True)
app=FastAPI(title='ABDOUUU TEAM VPS - Railway')

with sqlite3.connect(DB) as c:
    c.execute('''CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,name TEXT UNIQUE,type TEXT,entry TEXT,port INTEGER,container TEXT,status TEXT DEFAULT 'stopped',pid INTEGER DEFAULT 0,created TEXT DEFAULT CURRENT_TIMESTAMP)''')
    # Upgrade an older database created by the VPS/Docker version.
    cols={r[1] for r in c.execute('PRAGMA table_info(projects)')}
    if 'pid' not in cols: c.execute('ALTER TABLE projects ADD COLUMN pid INTEGER DEFAULT 0')

PROCS={}

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def auth(x_panel_token: str|None):
    if TOKEN=='change-me': raise HTTPException(500,'Set PANEL_TOKEN in Railway Variables')
    if x_panel_token!=TOKEN: raise HTTPException(401,'Invalid panel token')

def safe_name(s): return re.sub(r'[^a-zA-Z0-9_.-]+','-',s).strip('-')[:40] or 'project'

def detect(root):
    if (root/'package.json').exists():
        try:
            p=json.loads((root/'package.json').read_text())
            start=p.get('scripts',{}).get('start')
            if start: return 'node', 'npm-start'
        except Exception: pass
    for f in ('main.py','bot.py','app.py','index.py'):
        if (root/f).exists(): return 'python', f
    for f in ('index.js','bot.js','main.js','app.js'):
        if (root/f).exists(): return 'node', f
    return None,None

def safe_extract(z, root):
    names=z.namelist()
    for n in names:
        p=Path(n)
        if p.is_absolute() or '..' in p.parts: raise HTTPException(400,'Unsafe zip path')
    z.extractall(root)

def flatten_single_dir(root):
    # Accept ZIPs that contain one top-level folder.
    entries=[p for p in root.iterdir()]
    if len(entries)==1 and entries[0].is_dir():
        inner=entries[0]
        for p in list(inner.iterdir()): shutil.move(str(p), str(root/p.name))
        inner.rmdir()

def run_cmd(cmd, cwd, logfile, env=None):
    logfile.parent.mkdir(parents=True, exist_ok=True)
    f=logfile.open('ab')
    e=os.environ.copy(); e.update(env or {})
    # New process group lets stop/restart terminate child processes too.
    return subprocess.Popen(cmd,cwd=str(cwd),stdout=f,stderr=subprocess.STDOUT,env=e,start_new_session=True)

def install_dependencies(root, kind):
    if kind=='python' and (root/'requirements.txt').exists():
        venv=root/'.venv'
        if not venv.exists(): subprocess.run([sys.executable,'-m','venv',str(venv)],cwd=root,check=True)
        py=str(venv/('Scripts/python.exe' if os.name=='nt' else 'bin/python'))
        subprocess.run([py,'-m','pip','install','--disable-pip-version-check','-r','requirements.txt'],cwd=root,check=True)
        return py
    if kind=='node' and (root/'package.json').exists():
        subprocess.run(['npm','install','--omit=dev'],cwd=root,check=True)
    return None

def start_bot(pid):
    with db() as c: r=c.execute('SELECT * FROM projects WHERE id=? AND type="bot"',(pid,)).fetchone()
    if not r: raise HTTPException(404,'Bot not found')
    root=PROJECTS/pid; kind='python' if r['entry'].endswith('.py') else 'node'
    try:
        py=install_dependencies(root,kind)
        if kind=='python': cmd=[py or sys.executable,r['entry']]
        else: cmd=['npm','start'] if r['entry']=='npm-start' else ['node',r['entry']]
        proc=run_cmd(cmd,root,LOGS/f'{pid}.log')
        PROCS[pid]=proc
        with db() as c: c.execute('UPDATE projects SET status="running",pid=?,container="" WHERE id=?',(proc.pid,pid))
    except Exception as e:
        with db() as c: c.execute('UPDATE projects SET status="stopped",pid=0 WHERE id=?',(pid,))
        raise HTTPException(500,f'Failed to start bot: {e}')

def stop_bot(pid):
    proc=PROCS.pop(pid,None)
    pid_os=int(proc.pid) if proc else 0
    if not pid_os:
        with db() as c:
            r=c.execute('SELECT pid FROM projects WHERE id=? AND type="bot"',(pid,)).fetchone(); pid_os=int(r['pid'] or 0) if r else 0
    if pid_os:
        try: os.killpg(pid_os, signal.SIGTERM)
        except ProcessLookupError: pass
        except Exception:
            try: os.kill(pid_os, signal.SIGTERM)
            except Exception: pass
    with db() as c: c.execute('UPDATE projects SET status="stopped",pid=0 WHERE id=?',(pid,))

def refresh_status(data):
    for x in data:
        if x['type']!='bot': continue
        p=PROCS.get(x['id'])
        running=bool(p and p.poll() is None)
        if not running and x.get('pid'):
            try: os.kill(int(x['pid']),0); running=True
            except Exception: pass
        x['status']='running' if running else 'stopped'
        if not running and x.get('status')!='stopped':
            with db() as c: c.execute('UPDATE projects SET status="stopped",pid=0 WHERE id=?',(x['id'],))
    return data

@app.on_event('startup')
def startup():
    # Processes do not survive a Railway redeploy; mark old DB entries stopped.
    with db() as c: c.execute('UPDATE projects SET status="stopped",pid=0 WHERE type="bot"')

@app.get('/',response_class=HTMLResponse)
def home(): return (BASE/'static'/'index.html').read_text()

@app.get('/health')
def health(): return {'ok':True,'service':'abdouuu-team-vps'}

@app.get('/api/projects')
def list_projects(x_panel_token:str|None=Header(None)):
    auth(x_panel_token)
    with db() as c: data=[dict(x) for x in c.execute('SELECT * FROM projects ORDER BY created DESC')]
    return refresh_status(data)

@app.post('/api/upload')
async def upload(name:str=Form(...), kind:str=Form(...), file:UploadFile=File(...), x_panel_token:str|None=Header(None)):
    auth(x_panel_token)
    if kind not in ('bot','site'): raise HTTPException(400,'kind must be bot or site')
    if not file.filename or Path(file.filename).name!=file.filename: raise HTTPException(400,'Invalid filename')
    pid=uuid.uuid4().hex[:12]; safe=safe_name(name); root=(PROJECTS if kind=='bot' else SITES)/pid; root.mkdir(parents=True)
    dest=root/file.filename
    with dest.open('wb') as f:
        shutil.copyfileobj(file.file,f)
    if dest.suffix.lower()=='.zip':
        try:
            with zipfile.ZipFile(dest) as z: safe_extract(z,root)
        except zipfile.BadZipFile: shutil.rmtree(root,ignore_errors=True); raise HTTPException(400,'Invalid ZIP file')
        dest.unlink(); flatten_single_dir(root)
    if kind=='site':
        if not (root/'index.html').exists(): shutil.rmtree(root,ignore_errors=True); raise HTTPException(400,'Site must contain index.html')
        with db() as c: c.execute('INSERT INTO projects(id,name,type,entry,port,container,status,pid) VALUES(?,?,?,?,?,?,?,?)',(pid,safe,'site','index.html',0,'','running',0))
    else:
        k,e=detect(root)
        if not k: shutil.rmtree(root,ignore_errors=True); raise HTTPException(400,'Could not detect Python or Node entry file')
        with db() as c: c.execute('INSERT INTO projects(id,name,type,entry,port,container,status,pid) VALUES(?,?,?,?,?,?,?,?)',(pid,safe,'bot',e,0,'','stopped',0))
    return {'ok':True,'id':pid}

@app.post('/api/bots/{pid}/{action}')
def bot_action(pid:str,action:str,x_panel_token:str|None=Header(None)):
    auth(x_panel_token)
    with db() as c: r=c.execute('SELECT * FROM projects WHERE id=? AND type="bot"',(pid,)).fetchone()
    if not r: raise HTTPException(404,'Bot not found')
    if action=='start':
        stop_bot(pid); start_bot(pid)
    elif action=='stop': stop_bot(pid)
    elif action=='restart': stop_bot(pid); start_bot(pid)
    else: raise HTTPException(400,'Unknown action')
    return {'ok':True}

@app.get('/api/bots/{pid}/logs')
def logs(pid:str,x_panel_token:str|None=Header(None)):
    auth(x_panel_token)
    with db() as c: r=c.execute('SELECT id FROM projects WHERE id=? AND type="bot"',(pid,)).fetchone()
    if not r: raise HTTPException(404,'Bot not found')
    p=LOGS/f'{pid}.log'
    return {'logs':p.read_text(errors='replace')[-20000:] if p.exists() else ''}

@app.get('/site/{pid}/{path:path}')
def site(pid:str,path:str=''):
    with db() as c: r=c.execute('SELECT id FROM projects WHERE id=? AND type="site"',(pid,)).fetchone()
    if not r: raise HTTPException(404,'Site not found')
    root=(SITES/pid).resolve(); target=(root/(path or 'index.html')).resolve()
    if root not in target.parents and target!=root: raise HTTPException(403,'Forbidden')
    if not target.exists() or not target.is_file(): raise HTTPException(404,'File not found')
    return FileResponse(target)
