"""TBB Map — web địa giới, vol tồn và định mức bưu cục vùng Tây Bắc Bộ (GHN)."""
import io
import json
import os
import shutil
import sqlite3
import threading
from urllib.parse import unquote
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import vol as volmod

BASE = Path(__file__).parent
DATA = Path(os.environ.get("DATA_DIR", BASE.parent / "data"))
DATA.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA / "app.db"
VOL_PATH = DATA / "vol.json"
EDIT_PIN = os.environ.get("EDIT_PIN", "").strip()
ADMIN_PIN = os.environ.get("ADMIN_PIN", "").strip()
LOCK = threading.Lock()

app = FastAPI(title="TBB Map", docs_url=None, redoc_url=None)


# ---------------------------------------------------------------- database
@contextmanager
def db():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def now():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS bcdm(bc_id TEXT PRIMARY KEY, dm INTEGER, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS xdm(xa_id TEXT PRIMARY KEY, dm INTEGER, nv REAL, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS tuyen(id TEXT PRIMARY KEY, data TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS log(id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, action TEXT, target TEXT, detail TEXT, ip TEXT, who TEXT);
        """)
        seeded = c.execute("SELECT value FROM kv WHERE key='seeded'").fetchone()
        seed = BASE / "seed" / "state.json"
        if not seeded and seed.exists():
            s = json.loads(seed.read_text(encoding="utf-8"))
            c.execute("INSERT OR REPLACE INTO kv VALUES('chung',?)", (str(s.get("chung", 50)),))
            for k, v in s.get("bcdm", {}).items():
                c.execute("INSERT OR REPLACE INTO bcdm VALUES(?,?,?)", (k, int(v), now()))
            for k, v in s.get("xdm", {}).items():
                c.execute("INSERT OR REPLACE INTO xdm VALUES(?,?,?,?)", (k, int(v.get("dm") or 0), float(v.get("nv") or 0), now()))
            for t in s.get("tuyen", []):
                tid = t.pop("_id")
                c.execute("INSERT OR REPLACE INTO tuyen VALUES(?,?,?)", (tid, json.dumps(t, ensure_ascii=False), t.get("updated_at") or now()))
            c.execute("INSERT OR REPLACE INTO kv VALUES('seeded','1')")
            c.execute("INSERT OR REPLACE INTO kv VALUES('rev','1')")
    if not VOL_PATH.exists() and (BASE / "seed" / "vol.json").exists():
        shutil.copy(BASE / "seed" / "vol.json", VOL_PATH)


init_db()


def bump(c):
    r = c.execute("SELECT value FROM kv WHERE key='rev'").fetchone()
    rev = int(r["value"]) + 1 if r else 1
    c.execute("INSERT OR REPLACE INTO kv VALUES('rev',?)", (str(rev),))
    return rev


def log(c, req: Request, action, target, detail=""):
    ip = req.headers.get("x-forwarded-for", req.client.host if req.client else "")
    who = unquote(req.headers.get("x-user", ""))[:60]
    c.execute("INSERT INTO log(at,action,target,detail,ip,who) VALUES(?,?,?,?,?,?)", (now(), action, target, detail[:500], ip.split(",")[0], who))


def need_edit(pin):
    if EDIT_PIN and (pin or "").strip() not in (EDIT_PIN, ADMIN_PIN):
        raise HTTPException(401, "Sai hoặc thiếu mã PIN sửa.")


def need_admin(pin):
    if not ADMIN_PIN or (pin or "").strip() != ADMIN_PIN:
        raise HTTPException(401, "Sai hoặc thiếu mã PIN quản trị.")


# ---------------------------------------------------------------- read
@app.get("/api/rev")
def rev():
    with db() as c:
        r = c.execute("SELECT value FROM kv WHERE key='rev'").fetchone()
    return {"rev": int(r["value"]) if r else 0, "vol": VOL_PATH.stat().st_mtime if VOL_PATH.exists() else 0}


@app.get("/api/state")
def state():
    with db() as c:
        ch = c.execute("SELECT value FROM kv WHERE key='chung'").fetchone()
        r = c.execute("SELECT value FROM kv WHERE key='rev'").fetchone()
        bc = {x["bc_id"]: x["dm"] for x in c.execute("SELECT * FROM bcdm")}
        xa = {x["xa_id"]: {"dm": x["dm"], "nv": x["nv"]} for x in c.execute("SELECT * FROM xdm")}
        tu = [dict(json.loads(x["data"]), _id=x["id"]) for x in c.execute("SELECT * FROM tuyen ORDER BY updated_at DESC")]
    return {"chung": int(ch["value"]) if ch else 50, "bcdm": bc, "xdm": xa, "tuyen": tu,
            "rev": int(r["value"]) if r else 0, "edit_pin": bool(EDIT_PIN)}


@app.get("/api/vol")
def get_vol():
    if not VOL_PATH.exists():
        return {"meta": None, "bc": {}, "xa": {}}
    return FileResponse(VOL_PATH, media_type="application/json", headers={"Cache-Control": "no-cache"})


@app.get("/api/log")
def get_log(limit: int = 100):
    with db() as c:
        rows = [dict(x) for x in c.execute("SELECT at,action,target,detail,who FROM log ORDER BY id DESC LIMIT ?", (min(limit, 500),))]
    return rows


# ---------------------------------------------------------------- write
class Dm(BaseModel):
    dm: int = Field(0, ge=0, le=5000)


class Xdm(BaseModel):
    id: str = ""
    dm: int = Field(0, ge=0, le=5000)
    nv: float = Field(0, ge=0, le=50)


class Tuyen(BaseModel):
    ten_tuyen: str = Field(..., max_length=200)
    unit: str = Field(..., pattern="^(cu|moi)$")
    wards: list = Field(..., max_length=200)
    bc_ids: list = Field(default_factory=list, max_length=60)
    bc: str = Field("", max_length=600)
    nv_thieu: int = Field(0, ge=0, le=500)
    muc: str = Field("thieu", pattern="^(thieu|nghiem_trong)$")
    ghi_chu: str = Field("", max_length=1000)
    by: str = Field("", max_length=60)


@app.post("/api/check-pin")
def check_pin(body: dict):
    p = str(body.get("pin", "")).strip()
    return {"edit": (not EDIT_PIN) or p in (EDIT_PIN, ADMIN_PIN), "admin": bool(ADMIN_PIN) and p == ADMIN_PIN}


@app.put("/api/chung")
def put_chung(body: Dm, req: Request, x_pin: str = Header(None)):
    need_edit(x_pin)
    if body.dm < 1:
        raise HTTPException(400, "Định mức chung phải ≥ 1")
    with LOCK, db() as c:
        c.execute("INSERT OR REPLACE INTO kv VALUES('chung',?)", (str(body.dm),))
        log(c, req, "dinh_muc_chung", "", str(body.dm))
        return {"rev": bump(c)}


@app.put("/api/bcdm/{bc_id}")
def put_bcdm(bc_id: str, body: Dm, req: Request, x_pin: str = Header(None)):
    need_edit(x_pin)
    with LOCK, db() as c:
        if body.dm:
            c.execute("INSERT OR REPLACE INTO bcdm VALUES(?,?,?)", (bc_id, body.dm, now()))
        else:
            c.execute("DELETE FROM bcdm WHERE bc_id=?", (bc_id,))
        log(c, req, "dinh_muc_bc", bc_id, str(body.dm))
        return {"rev": bump(c)}


def _put_x(c, x: Xdm):
    if x.id not in volmod.MASTER:
        return False
    if x.dm or x.nv:
        c.execute("INSERT OR REPLACE INTO xdm VALUES(?,?,?,?)", (x.id, x.dm, x.nv, now()))
    else:
        c.execute("DELETE FROM xdm WHERE xa_id=?", (x.id,))
    return True


@app.put("/api/xdm/{xa_id}")
def put_xdm(xa_id: str, body: Xdm, req: Request, x_pin: str = Header(None)):
    need_edit(x_pin)
    body.id = xa_id
    with LOCK, db() as c:
        if not _put_x(c, body):
            raise HTTPException(404, "Không có xã này")
        log(c, req, "dinh_muc_xa", xa_id, f"dm={body.dm} nv={body.nv}")
        return {"rev": bump(c)}


@app.post("/api/xdm/batch")
def batch_xdm(items: list[Xdm], req: Request, x_pin: str = Header(None)):
    need_edit(x_pin)
    if len(items) > 1000:
        raise HTTPException(400, "Tối đa 1000 dòng")
    with LOCK, db() as c:
        ok = sum(1 for x in items if _put_x(c, x))
        log(c, req, "dinh_muc_xa_hang_loat", f"{ok} xã", "")
        return {"ok": ok, "rev": bump(c)}


@app.put("/api/tuyen/{tid}")
def put_tuyen(tid: str, body: Tuyen, req: Request, x_pin: str = Header(None)):
    need_edit(x_pin)
    if len(tid) > 40:
        raise HTTPException(400, "id")
    d = body.model_dump()
    d["updated_at"] = now()
    with LOCK, db() as c:
        c.execute("INSERT OR REPLACE INTO tuyen VALUES(?,?,?)", (tid, json.dumps(d, ensure_ascii=False), d["updated_at"]))
        log(c, req, "tuyen_luu", tid, f"{body.ten_tuyen} · thiếu {body.nv_thieu}")
        return {"rev": bump(c)}


@app.delete("/api/tuyen/{tid}")
def del_tuyen(tid: str, req: Request, x_pin: str = Header(None)):
    need_edit(x_pin)
    with LOCK, db() as c:
        r = c.execute("SELECT data FROM tuyen WHERE id=?", (tid,)).fetchone()
        c.execute("DELETE FROM tuyen WHERE id=?", (tid,))
        log(c, req, "tuyen_xoa", tid, json.loads(r["data"]).get("ten_tuyen", "") if r else "")
        return {"rev": bump(c)}


# ---------------------------------------------------------------- admin
@app.post("/api/admin/vol")
async def upload_vol(req: Request, file: UploadFile = File(...), x_pin: str = Header(None)):
    need_admin(x_pin)
    content = await file.read()
    if len(content) > 40 * 1024 * 1024:
        raise HTTPException(400, "File quá lớn (tối đa 40MB)")
    with db() as c:
        r = c.execute("SELECT value FROM kv WHERE key='learned'").fetchone()
    learned = json.loads(r["value"]) if r else json.loads((BASE / "ref" / "map_ten_xa.json").read_text(encoding="utf-8"))
    try:
        out, new_learned = volmod.process(content, file.filename or "", learned)
    except ValueError as e:
        raise HTTPException(400, str(e))
    learned.update(new_learned)
    tmp = VOL_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    if VOL_PATH.exists():
        shutil.copy(VOL_PATH, DATA / f"vol_{datetime.now():%Y%m%d_%H%M%S}.json")
    tmp.replace(VOL_PATH)
    with LOCK, db() as c:
        c.execute("INSERT OR REPLACE INTO kv VALUES('learned',?)", (json.dumps(learned, ensure_ascii=False),))
        log(c, req, "cap_nhat_vol", file.filename or "", f"{out['meta']['so_don']} đơn, ghép {out['meta']['ghep_duoc']}")
        bump(c)
    return out["meta"]


@app.get("/api/admin/backup.xlsx")
def backup(pin: str = ""):
    need_admin(pin)
    import pandas as pd
    st = state()
    M = volmod.MASTER
    names = {v["bc_id"]: v["bc"] for v in M.values()}
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as w:
        pd.DataFrame([{"Mã BC": k, "Bưu cục": names.get(k, ""), "Định mức": v} for k, v in st["bcdm"].items()]
                     + [{"Mã BC": "CHUNG", "Bưu cục": "Định mức chung", "Định mức": st["chung"]}]).to_excel(w, "Định mức BC", index=False)
        pd.DataFrame([{"ID GHN xã cũ": k, "Xã cũ": M.get(k, {}).get("ten", ""), "Huyện cũ": M.get(k, {}).get("huyen", ""),
                       "Bưu cục": M.get(k, {}).get("bc", ""), "Định mức xã": v["dm"] or None, "NV phụ trách": v["nv"] or None}
                      for k, v in st["xdm"].items()]).to_excel(w, "Định mức xã", index=False)
        pd.DataFrame([{"Tuyến": t["ten_tuyen"], "BC": t.get("bc", ""), "Đơn vị": "Xã cũ" if t["unit"] == "cu" else "Xã mới",
                       "Phường/xã": ", ".join(x.get("ten", "") for x in t["wards"]), "NV thiếu": t["nv_thieu"],
                       "Mức độ": "Nghiêm trọng" if t["muc"] == "nghiem_trong" else "Thiếu", "Ghi chú": t.get("ghi_chu", ""),
                       "Cập nhật": t.get("updated_at", "")} for t in st["tuyen"]]).to_excel(w, "Tuyến thiếu người", index=False)
        pd.DataFrame(get_log(500)).to_excel(w, "Nhật ký", index=False)
    bio.seek(0)
    fn = f"TBB_map_saoluu_{datetime.now():%Y%m%d_%H%M}.xlsx"
    return StreamingResponse(bio, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{fn}"'})


@app.get("/healthz")
def health():
    return {"ok": True}


app.mount("/data", StaticFiles(directory=BASE / "static" / "data"), name="data")


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html", headers={"Cache-Control": "no-cache"})


@app.exception_handler(HTTPException)
async def http_exc(_, exc: HTTPException):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
