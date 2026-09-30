import json, os, shutil, subprocess, tempfile, time
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="GitScope")
HERE = Path(__file__).resolve().parent
SEP = "\x1f"


def git(repo, *args, inp=None, env=None, check=True) -> bytes:
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, input=inp,
                       env={**os.environ, **(env or {})})
    if check and p.returncode:
        raise HTTPException(400, p.stderr.decode(errors="replace").strip() or "git failed")
    return p.stdout


def gs(repo, *args, **kw) -> str:
    return git(repo, *args, **kw).decode(errors="replace").strip()


def repo_of(path: str) -> str:
    p = Path(path).expanduser()
    if not p.is_dir():
        raise HTTPException(400, f"Folder not found: {path}")
    r = subprocess.run(["git", "-C", str(p), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if r.returncode:
        raise HTTPException(400, "That folder is not a git repository.")
    return r.stdout.strip()


def safe(rel: str) -> str:
    q = Path(rel)
    if not rel or q.is_absolute() or ".." in q.parts:
        raise HTTPException(400, "Invalid file path")
    return rel


def store(repo) -> Path:
    d = Path(gs(repo, "rev-parse", "--absolute-git-dir")) / "gitscope"
    d.mkdir(exist_ok=True)
    return d


def pins_of(repo):
    f = store(repo) / "pins.json"
    d = json.loads(f.read_text()) if f.exists() else {}
    return d if isinstance(d, dict) else {}


def is_local(repo, ref):
    return subprocess.run(["git", "-C", repo, "show-ref", "--verify", "--quiet", f"refs/heads/{ref}"]).returncode == 0


class Base(BaseModel):
    repo: str


@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")


@app.get("/api/info")
def info(repo: str):
    r = repo_of(repo)
    ok = lambda *a: gs(r, *a, check=False)
    fmt = SEP.join(["%H", "%an", "%ar", "%ad", "%s"])
    commit = ok("log", "-1", f"--format={fmt}")
    last = None
    if commit:
        h, an, ar, ad, s = commit.split(SEP)
        last = dict(hash=h, author=an, ago=ar, date=ad, subject=s,
                    stat=ok("show", "--stat", "--format=", "HEAD"))
    log = [dict(zip(["hash", "author", "ago", "subject"], l.split(SEP)))
           for l in ok("log", "-20", f"--format=%h{SEP}%an{SEP}%ar{SEP}%s").splitlines() if l]
    stashes = [dict(zip(["ref", "msg", "ago"], l.split(SEP)))
               for l in ok("stash", "list", f"--format=%gd{SEP}%s{SEP}%ar").splitlines() if l]
    local = ok("for-each-ref", "--format=%(refname:short)", "refs/heads").splitlines()
    remote = [b for b in ok("for-each-ref", "--format=%(refname:short)", "refs/remotes").splitlines()
              if not b.endswith("/HEAD")]
    return dict(root=r, branch=ok("branch", "--show-current"), remote_url=ok("remote", "get-url", "origin"),
                local=local, remote=remote, last=last, log=log, stashes=stashes,
                status=ok("status", "--short"), pins=pins_of(r))


@app.post("/api/fetch")
def fetch(b: Base):
    r = repo_of(b.repo)
    git(r, "fetch", "origin", "--prune")
    return {"ok": True}


class Ref(Base):
    ref: str


@app.post("/api/stash/apply")
def stash_apply(b: Ref):
    r = repo_of(b.repo)
    git(r, "stash", "apply", b.ref)
    return {"ok": True}


@app.post("/api/checkout")
def checkout(b: Ref):
    r = repo_of(b.repo)
    git(r, "checkout", b.ref)
    return {"ok": True}


@app.get("/api/compare")
def compare(repo: str, a: str, b: str):
    r = repo_of(repo)

    def tree(ref):
        out = git(r, "ls-tree", "-r", "-z", ref).decode(errors="replace")
        return {e.split("\t", 1)[1]: e.split()[2] for e in out.split("\0") if e}

    ta, tb = tree(a), tree(b)
    files = []
    for p in sorted(set(ta) | set(tb)):
        st = "same" if ta.get(p) == tb.get(p) else ("only_b" if p not in ta else "only_a" if p not in tb else "diff")
        files.append(dict(path=p, status=st))
    return dict(files=files)


@app.get("/api/file")
def file(repo: str, ref: str, path: str):
    r = repo_of(repo)
    p = subprocess.run(["git", "-C", r, "show", f"{ref}:{safe(path)}"], capture_output=True)
    if p.returncode:
        return dict(exists=False, binary=False, content="")
    if b"\0" in p.stdout[:8000]:
        return dict(exists=True, binary=True, content="")
    return dict(exists=True, binary=False, content=p.stdout.decode(errors="replace"))


def ref_bytes(r, ref, p):
    x = subprocess.run(["git", "-C", r, "show", f"{ref}:{p}"], capture_output=True)
    return None if x.returncode else x.stdout


def commit_files(r, branch, files, msg):
    files = {safe(p): d for p, d in files.items() if ref_bytes(r, branch, p) != d}
    if not files:
        return []
    if branch == gs(r, "branch", "--show-current"):
        for p, d in files.items():
            f = Path(r) / p
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(d)
        git(r, "add", "--", *files)
        git(r, "commit", "-m", msg, "--", *files)
    else:
        ref, idx = f"refs/heads/{branch}", tempfile.mktemp()
        env = {"GIT_INDEX_FILE": idx}
        try:
            parent = gs(r, "rev-parse", ref)
            git(r, "read-tree", ref, env=env)
            for p, d in files.items():
                sha = gs(r, "hash-object", "-w", "--stdin", inp=d)
                git(r, "update-index", "--add", "--cacheinfo", f"100644,{sha},{p}", env=env)
            new = gs(r, "commit-tree", gs(r, "write-tree", env=env), "-p", parent, "-m", msg)
            git(r, "update-ref", ref, new, parent)
        finally:
            if os.path.exists(idx):
                os.remove(idx)
    return list(files)


class Commit(Base):
    branch: str
    path: str
    content: str
    message: str


@app.post("/api/commit")
def commit(b: Commit):
    r = repo_of(b.repo)
    if not is_local(r, b.branch):
        raise HTTPException(400, "Remote branches are read-only. Edit a local branch instead.")
    commit_files(r, b.branch, {b.path: b.content.encode()}, b.message)
    return {"ok": True}


class PinReq(Base):
    branch: str
    path: str
    pinned: bool


@app.post("/api/pin")
def pin(b: PinReq):
    r = repo_of(b.repo)
    d = pins_of(r)
    s = set(d.get(b.branch, [])) - {safe(b.path)}
    if b.pinned:
        s.add(b.path)
    d[b.branch] = sorted(s)
    if not d[b.branch]:
        del d[b.branch]
    (store(r) / "pins.json").write_text(json.dumps(d))
    return {"pins": d}


def make_backup(r, branch):
    pins = pins_of(r).get(branch, [])
    if not pins:
        return None, []
    cur = gs(r, "branch", "--show-current")
    bid = time.strftime("%Y%m%d-%H%M%S") + "-" + branch.replace("/", "_")
    d, saved = store(r) / "backups" / bid, []
    for p in pins:
        f = Path(r) / p
        data = f.read_bytes() if branch == cur and f.is_file() else ref_bytes(r, branch, p)
        if data is None:
            continue
        (d / "files" / p).parent.mkdir(parents=True, exist_ok=True)
        (d / "files" / p).write_bytes(data)
        saved.append(p)
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps(dict(branch=branch, files=saved, time=time.strftime("%Y-%m-%d %H:%M:%S"))))
    return bid, saved


def restore_from(r, branch, bid):
    d = store(r) / "backups" / Path(bid).name
    if not (d / "meta.json").exists():
        raise HTTPException(404, "Backup not found")
    meta = json.loads((d / "meta.json").read_text())
    files = {p: (d / "files" / p).read_bytes() for p in meta["files"]}
    return commit_files(r, branch, files, "Restore pinned files (GitScope)")


class Target(Base):
    target: str


@app.post("/api/prepare")
def prepare(b: Target):
    """
    sTep 1
    back up every pinned file of the target branch
    """
    bid, saved = make_backup(repo_of(b.repo), b.target)
    return dict(id=bid, files=saved)


class Merge(Base):
    source: str
    target: str
    backup_id: Optional[str] = None
    restore: bool = True


@app.post("/api/hardmerge")
def hardmerge(b: Merge):
    """
    
    Make brach exactly identical to source; 
    optionally put target's pinned files back

    
    """
    r = repo_of(b.repo)
    if b.source == b.target:
        raise HTTPException(400, "Choose two different branches.")
    if not is_local(r, b.target):
        raise HTTPException(400, "The target must be a local branch.")
    sha = gs(r, "rev-parse", b.source + "^{commit}")
    old = gs(r, "rev-parse", "refs/heads/" + b.target)
    if b.target == gs(r, "branch", "--show-current"):
        git(r, "reset", "--hard", sha)
    else:
        git(r, "update-ref", "refs/heads/" + b.target, sha)
    restored = restore_from(r, b.target, b.backup_id) if (b.restore and b.backup_id) else []
    return dict(old=old, restored=restored)


class RestoreReq(Base):
    branch: str
    id: Optional[str] = None


@app.post("/api/restore_pins")
def restore_pins(b: RestoreReq):
    r = repo_of(b.repo)
    if not is_local(r, b.branch):
        raise HTTPException(400, "Choose a local branch.")
    bid = b.id or next((x["id"] for x in list_backups(r) if x["branch"] == b.branch and x["files"]), None)
    if not bid:
        raise HTTPException(404, f"No pinned-file backup found for {b.branch}.")
    return dict(id=bid, restored=restore_from(r, b.branch, bid))


def list_backups(r):
    root, out = store(r) / "backups", []
    if root.exists():
        for d in sorted(root.iterdir(), reverse=True):
            if (d / "meta.json").exists():
                out.append(dict(id=d.name, **json.loads((d / "meta.json").read_text())))
    return out


@app.get("/api/backups")
def backups(repo: str):
    return list_backups(repo_of(repo))
