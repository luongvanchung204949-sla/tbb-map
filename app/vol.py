"""Xử lý báo cáo tồn đọng lấy/giao/trả -> số liệu vol theo BC, xã cũ, xã mới.

Đầu vào: file Excel xuất từ hệ thống (cột: Mã bưu cục, Mã đơn hàng, Loại đơn,
Khách hàng, Phường/xã, Trạng thái, Thời gian tồn đọng). Dòng tiêu đề được tự dò.
"""
import io
import json
import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

VN = ZoneInfo("Asia/Ho_Chi_Minh")
from pathlib import Path

import pandas as pd

REF = Path(__file__).parent / "ref"
MASTER = json.loads((REF / "master.json").read_text(encoding="utf-8"))

# Quy đổi tên huyện/xã hệ thống GHN -> tên trong file địa giới
DIST = {
    "huyện nậm nhùm": "huyện nậm nhùn",
    "huyện mộc châu": "thị xã mộc châu",
    "huyện sa pa": "thị xã sa pa",
    "huyện mù căng chải": "huyện mù cang chải",
}
XA = {
    ("thị trấn mộc châu", "thị xã mộc châu"): "91288",
    ("thị trấn nông trường mộc châu", "thị xã mộc châu"): "91287",
    ("xã sáng nhè", "huyện tủa chùa"): "620606",
    ("xã bun nưa", "huyện mường tè"): "70502",
}
PRE = re.compile(r"^(xã|phường|thị trấn nông trường|thị trấn)\s+")


def full(s):
    s = unicodedata.normalize("NFC", str(s)).lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s.replace("thị trấn nt ", "thị trấn nông trường ").replace("thị trấn n.t ", "thị trấn nông trường ")


def ascii_(s):
    s = unicodedata.normalize("NFD", full(s))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").replace("đ", "d")


def _build_keys():
    k1, k2, k3 = {}, {}, {}
    for xid, r in MASTER.items():
        for nm in {r["ten"], r.get("ten_dm") or ""} - {""}:
            k1.setdefault((full(nm), full(r["huyen"])), xid)
            k2.setdefault((ascii_(nm), ascii_(r["huyen"])), set()).add(xid)
            k3.setdefault((PRE.sub("", full(nm)), full(r["huyen"])), set()).add(xid)
    return k1, k2, k3


K1, K2, K3 = _build_keys()


def match(xa, hu, learned):
    """Trả về (id xã cũ | None, cách ghép)."""
    raw = f"{xa}, {hu}"
    if raw in learned:
        return learned[raw], "Khớp (bảng tên)"
    if not isinstance(hu, str) or not hu.strip():
        return None, "Thiếu huyện"
    a, b = full(xa), DIST.get(full(hu), full(hu))
    if (a, b) in XA:
        return XA[(a, b)], "Khớp (quy đổi)"
    if (a, b) in K1:
        return K1[(a, b)], "Khớp"
    s = K2.get((ascii_(xa), ascii_(b)))
    if s and len(s) == 1:
        return next(iter(s)), "Khớp (khác dấu)"
    s = K3.get((PRE.sub("", a), b))
    if s and len(s) == 1:
        return next(iter(s)), "Khớp (khác cấp)"
    return None, "Không thuộc danh sách xã TBB"


def _read(content: bytes, is_csv: bool = False) -> pd.DataFrame:
    if is_csv:
        raw = pd.read_csv(io.BytesIO(content), header=None, dtype=str, keep_default_na=False, na_values=[""])
    else:
        raw = pd.read_excel(io.BytesIO(content), header=None, dtype=str)
    hdr = None
    for i in range(min(15, len(raw))):
        vals = [str(v).strip() for v in raw.iloc[i].tolist()]
        if any(v.endswith("Mã bưu cục") for v in vals) and "Phường/xã" in vals:
            hdr = i
            break
    if hdr is None:
        raise ValueError("Không tìm thấy dòng tiêu đề có 'Mã bưu cục' và 'Phường/xã'.")
    df = raw.iloc[hdr + 1:].copy()
    df.columns = ["Mã bưu cục" if str(c).strip().endswith("Mã bưu cục") else str(c).strip() for c in raw.iloc[hdr].tolist()]
    need = ["Mã bưu cục", "Mã đơn hàng", "Loại đơn", "Phường/xã", "Thời gian tồn đọng"]
    miss = [c for c in need if c not in df.columns]
    if miss:
        raise ValueError("Thiếu cột: " + ", ".join(miss))
    df = df.dropna(subset=["Mã đơn hàng"])
    return df.drop_duplicates(["Mã đơn hàng", "Loại đơn", "Mã bưu cục", "Phường/xã"])


def snapshot_time(filename: str):
    m = re.search(r"(\d{4}-\d{2}-\d{2})_at_(\d{2})_(\d{2})", filename or "")
    if m:
        return f"{m.group(1)}T{m.group(2)}:{m.group(3)}:00"
    return datetime.now(VN).strftime("%Y-%m-%dT%H:%M:00")


def process(content: bytes, filename: str, learned: dict, is_csv: bool = False, snapshot: str = None):
    df = _read(content, is_csv)
    sp = df["Phường/xã"].astype(str).str.rsplit(",", n=1, expand=True)
    df["xa"] = sp[0].str.strip()
    df["huyen"] = sp[1].str.strip() if sp.shape[1] > 1 else None
    cache = {}
    res = [cache.setdefault((a, h), match(a, h, learned)) for a, h in zip(df["xa"], df["huyen"])]
    df["xid"] = [r[0] for r in res]
    df["cach"] = [r[1] for r in res]
    lo = pd.to_numeric(df["Thời gian tồn đọng"].astype(str).str.split("_").str[0], errors="coerce").fillna(0)
    df["h"] = lo
    lt = df["Loại đơn"].astype(str)
    df["grp"] = lt.map(lambda s: "Giao" if s.startswith("Giao") or s.startswith("Ưu tiên giao") else s)
    df["tre"] = lt.eq("Ưu tiên giao/đã trễ")
    df["bc_terr"] = df["xid"].map(lambda i: MASTER[i]["bc_id"] if i in MASTER else None)
    df["lech"] = df["bc_terr"].notna() & (df["bc_terr"] != df["Mã bưu cục"])

    def agg(g):
        G = g["grp"] == "Giao"
        return {
            "giao": int(G.sum()), "tre": int(g["tre"].sum()),
            "lay": int((g["grp"] == "Lấy").sum()), "tra": int((g["grp"] == "Trả").sum()),
            "g24": int((G & (g["h"] >= 24)).sum()), "g72": int((G & (g["h"] >= 72)).sum()),
        }

    bc = {k: agg(g) for k, g in df.groupby("Mã bưu cục")}
    for k, n in df[df["lech"]].groupby("Mã bưu cục").size().items():
        bc.setdefault(k, {})["lech"] = int(n)
    m = df[df["xid"].notna()]
    xa = {k: agg(g) for k, g in m.groupby("xid")}
    new_learned = {f"{a}, {h}": i for a, h, i in zip(m["xa"], m["huyen"], m["xid"]) if isinstance(h, str)}
    un = (df[df["xid"].isna()].groupby(["Phường/xã", "Mã bưu cục"]).size()
          .sort_values(ascending=False).reset_index(name="so_don"))
    meta = {
        "snapshot": snapshot or snapshot_time(filename), "file": filename,
        "uploaded_at": datetime.now(VN).strftime("%Y-%m-%dT%H:%M:%S"),
        "so_don": int(len(df)), "ghep_duoc": int(df["xid"].notna().sum()),
        "giao": int((df["grp"] == "Giao").sum()),
        "chua_ghep": un.head(200).to_dict("records"),
        "lech": int(df["lech"].sum()),
    }
    return {"meta": meta, "bc": bc, "xa": xa}, new_learned
