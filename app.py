"""
FishyBox（FX）—— 本地 Prompt 资产管理系统 · 后端（FastAPI + SQLite）

主功能：Prompt 的增删查
隐私库：PBKDF2（60 万次）+ Fernet 加密，Sentinel 校验主密码，密钥/Token 只存内存

源码运行：
    uvicorn app:app
打包成 exe：
    由 launcher.py 启动（见 launcher.py 里的打包命令）
"""
import base64
import gc
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

# 路径处理：兼容「源码运行」和「PyInstaller 打包成 exe」两种形态
if getattr(sys, "frozen", False):
    # 打包后：static 资源被解压到临时目录；数据放到 exe 同目录
    STATIC_DIR = Path(sys._MEIPASS) / "static"
    BASE_DIR = Path(sys.executable).parent
else:
    # 源码运行：都以 app.py 所在目录为基准
    STATIC_DIR = Path(__file__).parent / "static"
    BASE_DIR = Path(__file__).parent

# 数据目录：database/ 存数据库，backup/ 存手动备份（时间戳文件夹）
DB_DIR = BASE_DIR / "database"
DB_PATH = DB_DIR / "prompts.db"
BACKUP_DIR = BASE_DIR / "backup"
DB_DIR.mkdir(exist_ok=True)
BACKUP_DIR.mkdir(exist_ok=True)

# 兼容旧版本：把根目录的 prompts.db 自动迁到 database/
_legacy_db = BASE_DIR / "prompts.db"
if _legacy_db.exists() and not DB_PATH.exists():
    try:
        shutil.move(str(_legacy_db), str(DB_PATH))
    except Exception:
        pass

# 加密常量
SENTINEL_PLAINTEXT = "fishybox-sentinel"  # 用于校验主密码的固定明文
PBKDF2_ITERATIONS = 600_000               # PBKDF2 迭代次数（OWASP 建议 ≥ 60 万）


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """应用退出时清理内存中的密钥与 Token。"""
    yield
    _app.state.vault_key = None
    _app.state.vault_token = None
    gc.collect()


app = FastAPI(title="FishyBox", lifespan=lifespan)

# 会话状态：解密密钥与 Token 只存内存，进程结束即销毁（绝不落盘）
app.state.vault_key = None
app.state.vault_token = None
app.state.last_heartbeat = time.time()  # 心跳时间：页面关闭后 launcher 据此自动退出


def get_db() -> sqlite3.Connection:
    """每次请求新建连接、用完关闭，避免多线程下 SQLite 连接冲突。"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """首次运行时自动建表（已存在则跳过）。"""
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS prompts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT    NOT NULL,
            category    TEXT    DEFAULT '',
            content     TEXT    NOT NULL,
            created_at  TEXT    DEFAULT (datetime('now', 'localtime'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS vault (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL,
            username    TEXT DEFAULT '',
            password    TEXT DEFAULT '',
            notes       TEXT DEFAULT '',
            created_at  TEXT DEFAULT (datetime('now', 'localtime'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS vault_meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tags (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name_zh     TEXT    NOT NULL,
            name_en     TEXT    DEFAULT '',
            sort_order  INTEGER DEFAULT 0
        )
        """
    )
    # 首次运行插入默认快捷标签
    if conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0] == 0:
        defaults = [
            ("人设卡", "Persona"),
            ("代码", "Code"),
            ("日志", "Log"),
            ("写作", "Write"),
            ("翻译", "Translate"),
            ("学习", "Study"),
            ("优质提示词", "Premium"),
        ]
        for i, (zh, en) in enumerate(defaults):
            conn.execute(
                "INSERT INTO tags (name_zh, name_en, sort_order) VALUES (?, ?, ?)",
                (zh, en, i),
            )
    conn.commit()
    conn.close()


init_db()


# ============ Prompt 主功能 ============

class PromptCreate(BaseModel):
    """新增 Prompt 时前端提交的 JSON 结构。"""
    title: str
    category: str = ""
    content: str


@app.post("/api/prompts")
def create_prompt(p: PromptCreate):
    """新增一条 Prompt。"""
    title = p.title.strip()
    content = p.content.strip()
    if not title or not content:
        raise HTTPException(status_code=400, detail="标题和内容不能为空")

    conn = get_db()
    cur = conn.execute(
        "INSERT INTO prompts (title, category, content) VALUES (?, ?, ?)",
        (title, p.category.strip(), content),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return {"ok": True, "id": new_id}


@app.get("/api/prompts")
def list_prompts(q: str = ""):
    """查询列表；带 q 时在标题和内容里做子串模糊匹配。"""
    conn = get_db()
    if q.strip():
        like = f"%{q.strip()}%"
        rows = conn.execute(
            "SELECT * FROM prompts WHERE title LIKE ? OR content LIKE ? ORDER BY id DESC",
            (like, like),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM prompts ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.delete("/api/prompts/{pid}")
def delete_prompt(pid: int):
    """删除一条 Prompt。"""
    conn = get_db()
    cur = conn.execute("DELETE FROM prompts WHERE id = ?", (pid,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="该记录不存在")
    return {"ok": True}


# ============ 快捷标签 ============

class TagCreate(BaseModel):
    """新增标签。"""
    name_zh: str
    name_en: str = ""


@app.get("/api/tags")
def list_tags():
    """返回全部快捷标签（按排序）。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name_zh, name_en, sort_order FROM tags ORDER BY sort_order, id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/tags")
def add_tag(t: TagCreate):
    """新增一个标签。"""
    zh = t.name_zh.strip()
    if not zh:
        raise HTTPException(status_code=400, detail="标签名不能为空")
    if len(zh) > 7:
        raise HTTPException(status_code=400, detail="标签最多 7 个字")
    conn = get_db()
    if conn.execute("SELECT id FROM tags WHERE name_zh = ?", (zh,)).fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="标签已存在")
    max_order = conn.execute("SELECT COALESCE(MAX(sort_order), -1) FROM tags").fetchone()[0]
    conn.execute(
        "INSERT INTO tags (name_zh, name_en, sort_order) VALUES (?, ?, ?)",
        (zh, t.name_en.strip(), max_order + 1),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@app.delete("/api/tags/{tag_id}")
def delete_tag(tag_id: int):
    """删除一个标签。"""
    conn = get_db()
    cur = conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="该标签不存在")
    return {"ok": True}


class TagOrder(BaseModel):
    """拖拽排序时提交的标签 id 顺序。"""
    ids: list[int]


@app.post("/api/tags/order")
def reorder_tags(o: TagOrder):
    """按提交的顺序重排标签。"""
    conn = get_db()
    for i, tid in enumerate(o.ids):
        conn.execute("UPDATE tags SET sort_order = ? WHERE id = ?", (i, tid))
    conn.commit()
    conn.close()
    return {"ok": True}


# ============ 加密隐私库 ============

def derive_key(password: str, salt: bytes) -> bytes:
    """由主密码 + 盐派生 32 字节 Fernet 密钥。"""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def get_vault_meta(key: str) -> str:
    """读取隐私库元数据（盐 / sentinel）；不存在返回空字符串。"""
    conn = get_db()
    row = conn.execute("SELECT value FROM vault_meta WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else ""


def set_vault_meta(key: str, value: str) -> None:
    """写入隐私库元数据（存在则覆盖）。"""
    conn = get_db()
    conn.execute(
        "INSERT INTO vault_meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


def _vault_fernet(token: str) -> Fernet:
    """校验 Token 并返回解密器；未解锁 / Token 错误则 401。"""
    if not token or token != app.state.vault_token or app.state.vault_key is None:
        raise HTTPException(status_code=401, detail="未解锁或已锁定")
    return Fernet(app.state.vault_key)


def _validate_password(password: str):
    """校验主密码规则：8~32 位且至少一个特殊字符；合法返回 None，否则返回错误信息。"""
    if len(password) < 8:
        return "至少 8 位"
    if len(password) > 32:
        return "最多 32 位"
    specials = "!@#$%^&*()_+-=[]{};':\"\\|,.<>/?`~￥、。，"
    if not any(c in specials for c in password):
        return "需包含至少一个特殊字符"
    return None


class VaultPassword(BaseModel):
    password: str


class VaultItemCreate(BaseModel):
    title: str
    username: str = ""
    password: str = ""
    notes: str = ""


@app.get("/api/vault/status")
def vault_status():
    """返回隐私库是否已初始化（用于前端决定「设置主密码」还是「解锁」）。"""
    return {"initialized": bool(get_vault_meta("salt"))}


@app.post("/api/vault/setup")
def vault_setup(p: VaultPassword):
    """首次设置主密码：生成盐 + 派生密钥 + 存 sentinel。"""
    password = p.password.strip()
    err = _validate_password(password)
    if err:
        raise HTTPException(status_code=400, detail=err)
    if get_vault_meta("salt"):
        raise HTTPException(status_code=400, detail="已初始化")

    salt = os.urandom(16)
    key = derive_key(password, salt)
    f = Fernet(key)
    sentinel = f.encrypt(SENTINEL_PLAINTEXT.encode("utf-8")).decode("utf-8")

    set_vault_meta("salt", base64.b64encode(salt).decode("utf-8"))
    set_vault_meta("sentinel", sentinel)

    token = secrets.token_hex(32)
    app.state.vault_key = key
    app.state.vault_token = token
    return {"ok": True, "token": token}


@app.post("/api/vault/unlock")
def vault_unlock(p: VaultPassword):
    """解锁：派生密钥 → 尝试解密 sentinel → 验证通过则发 Token。"""
    salt_b64 = get_vault_meta("salt")
    if not salt_b64:
        raise HTTPException(status_code=400, detail="未初始化")

    salt = base64.b64decode(salt_b64)
    key = derive_key(p.password.strip(), salt)
    f = Fernet(key)
    try:
        plaintext = f.decrypt(get_vault_meta("sentinel").encode("utf-8")).decode("utf-8")
    except Exception:
        raise HTTPException(status_code=401, detail="密码错误")
    if plaintext != SENTINEL_PLAINTEXT:
        raise HTTPException(status_code=401, detail="密码错误")

    token = secrets.token_hex(32)
    app.state.vault_key = key
    app.state.vault_token = token
    return {"ok": True, "token": token}


@app.post("/api/vault/lock")
def vault_lock(x_vault_token: str = Header(None)):
    """锁定：清空内存中的密钥与 Token。"""
    _vault_fernet(x_vault_token)
    app.state.vault_key = None
    app.state.vault_token = None
    gc.collect()
    return {"ok": True}


@app.get("/api/vault/items")
def vault_list(x_vault_token: str = Header(None)):
    """列出所有条目（解密后返回）。"""
    f = _vault_fernet(x_vault_token)
    conn = get_db()
    rows = conn.execute("SELECT * FROM vault ORDER BY id DESC").fetchall()
    conn.close()
    return [
        {
            "id": r["id"],
            "title": f.decrypt(r["title"].encode("utf-8")).decode("utf-8"),
            "username": f.decrypt(r["username"].encode("utf-8")).decode("utf-8"),
            "password": f.decrypt(r["password"].encode("utf-8")).decode("utf-8"),
            "notes": f.decrypt(r["notes"].encode("utf-8")).decode("utf-8"),
        }
        for r in rows
    ]


@app.post("/api/vault/items")
def vault_create(p: VaultItemCreate, x_vault_token: str = Header(None)):
    """新增条目（字段加密后入库）。"""
    f = _vault_fernet(x_vault_token)
    title = p.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")

    conn = get_db()
    cur = conn.execute(
        "INSERT INTO vault (title, username, password, notes) VALUES (?, ?, ?, ?)",
        (
            f.encrypt(title.encode("utf-8")).decode("utf-8"),
            f.encrypt(p.username.encode("utf-8")).decode("utf-8"),
            f.encrypt(p.password.encode("utf-8")).decode("utf-8"),
            f.encrypt(p.notes.encode("utf-8")).decode("utf-8"),
        ),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return {"ok": True, "id": new_id}


@app.delete("/api/vault/items/{vid}")
def vault_delete(vid: int, x_vault_token: str = Header(None)):
    """删除条目。"""
    _vault_fernet(x_vault_token)
    conn = get_db()
    cur = conn.execute("DELETE FROM vault WHERE id = ?", (vid,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="不存在")
    return {"ok": True}


@app.post("/api/vault/reset")
def vault_reset(p: VaultPassword, x_vault_token: str = Header(None)):
    """重置主密码：用旧密钥解密所有条目，再用新密钥重新加密（数据不丢）。"""
    old_f = _vault_fernet(x_vault_token)
    new_password = p.password.strip()
    err = _validate_password(new_password)
    if err:
        raise HTTPException(status_code=400, detail=err)

    new_salt = os.urandom(16)
    new_key = derive_key(new_password, new_salt)
    new_f = Fernet(new_key)

    conn = get_db()
    rows = conn.execute("SELECT * FROM vault").fetchall()
    for r in rows:
        plain = (
            old_f.decrypt(r["title"].encode("utf-8")).decode("utf-8"),
            old_f.decrypt(r["username"].encode("utf-8")).decode("utf-8"),
            old_f.decrypt(r["password"].encode("utf-8")).decode("utf-8"),
            old_f.decrypt(r["notes"].encode("utf-8")).decode("utf-8"),
        )
        conn.execute(
            "UPDATE vault SET title=?, username=?, password=?, notes=? WHERE id=?",
            (
                new_f.encrypt(plain[0].encode("utf-8")).decode("utf-8"),
                new_f.encrypt(plain[1].encode("utf-8")).decode("utf-8"),
                new_f.encrypt(plain[2].encode("utf-8")).decode("utf-8"),
                new_f.encrypt(plain[3].encode("utf-8")).decode("utf-8"),
                r["id"],
            ),
        )
    conn.execute(
        "UPDATE vault_meta SET value=? WHERE key='salt'",
        (base64.b64encode(new_salt).decode("utf-8"),),
    )
    conn.execute(
        "UPDATE vault_meta SET value=? WHERE key='sentinel'",
        (new_f.encrypt(SENTINEL_PLAINTEXT.encode("utf-8")).decode("utf-8"),),
    )
    conn.commit()
    conn.close()

    token = secrets.token_hex(32)
    app.state.vault_key = new_key
    app.state.vault_token = token
    return {"ok": True, "token": token}


# ============ 剪贴板自动清除 ============

class ClipSetting(BaseModel):
    """剪贴板清除设置：password 用于验证，sec 为清除秒数（0=关闭）。"""
    password: str
    sec: int = 30


@app.get("/api/vault/clipboard")
def get_clipboard_setting():
    """读取剪贴板清除秒数（0=关闭）。"""
    val = get_vault_meta("clip_clear_sec") or "0"
    try:
        sec = int(val)
    except ValueError:
        sec = 0
    return {"sec": sec}


@app.post("/api/vault/clipboard")
def set_clipboard_setting(s: ClipSetting):
    """修改剪贴板清除秒数：开启需验证主密码；关闭（sec=0）可直接操作。"""
    sec = int(s.sec)
    if sec < 0:
        sec = 0
    if sec != 0 and sec < 5:
        sec = 5
    if sec > 0:
        salt_b64 = get_vault_meta("salt")
        if not salt_b64:
            raise HTTPException(status_code=400, detail="尚未设置主密码")
        salt = base64.b64decode(salt_b64)
        key = derive_key(s.password, salt)
        f = Fernet(key)
        try:
            plaintext = f.decrypt(get_vault_meta("sentinel").encode("utf-8")).decode("utf-8")
        except Exception:
            raise HTTPException(status_code=401, detail="主密码错误")
        if plaintext != SENTINEL_PLAINTEXT:
            raise HTTPException(status_code=401, detail="主密码错误")
    set_vault_meta("clip_clear_sec", str(sec))
    return {"ok": True, "sec": sec}


# ============ 数据库备份（database/ → backup/时间戳/） ============

@app.post("/api/backup")
def backup_database():
    """把 database 目录整体复制到 backup/时间戳/。"""
    ts = time.strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / ts
    if dest.exists():
        raise HTTPException(status_code=400, detail="该时间的备份已存在")
    try:
        shutil.copytree(DB_DIR, dest)
    except Exception as e:
        raise HTTPException(status_code=500, detail="备份失败: " + str(e))
    return {"ok": True, "name": ts, "path": str(dest)}


@app.get("/api/backup/list")
def list_backups():
    """列出已有的备份（新的在前）。"""
    items = []
    if BACKUP_DIR.exists():
        for d in sorted(BACKUP_DIR.iterdir(), reverse=True):
            if d.is_dir():
                items.append({"name": d.name})
    return {"items": items}


# ============ 备份 / 导入导出 ============

class ImportText(BaseModel):
    """导入 Prompt 时提交的 Markdown 文本。"""
    text: str


class VaultImport(BaseModel):
    """导入隐私库备份：备份密码 + 加密数据。"""
    password: str
    data: str


@app.get("/api/export/prompts")
def export_prompts():
    """导出全部 Prompt 为 Markdown 文本（带分隔标记，便于再导入）。"""
    conn = get_db()
    rows = conn.execute("SELECT title, category, content FROM prompts ORDER BY id").fetchall()
    conn.close()
    parts = ["# FishyBox Prompt 备份\n\n"]
    for r in rows:
        parts.append("<!-- FISHYBOX-PROMPT -->\n")
        parts.append("## " + r["title"] + "\n")
        parts.append("分类: " + (r["category"] or "") + "\n\n")
        parts.append(r["content"] + "\n\n")
        parts.append("<!-- /FISHYBOX-PROMPT -->\n")
    return {"text": "".join(parts), "count": len(rows)}


@app.post("/api/import/prompts")
def import_prompts(p: ImportText):
    """从 Markdown 文本导入 Prompt。"""
    blocks = p.text.split("<!-- FISHYBOX-PROMPT -->")
    conn = get_db()
    added = 0
    for b in blocks:
        b = b.split("<!-- /FISHYBOX-PROMPT -->")[0]
        title = ""
        category = ""
        content_lines = []
        seen_title = False
        for ln in b.splitlines():
            if not seen_title and ln.startswith("## "):
                title = ln[3:].strip()
                seen_title = True
                continue
            if seen_title and ln.startswith("分类:"):
                category = ln[3:].strip()
                continue
            if seen_title:
                content_lines.append(ln)
        content = "\n".join(content_lines).strip()
        if title and content:
            conn.execute(
                "INSERT INTO prompts (title, category, content) VALUES (?, ?, ?)",
                (title, category, content),
            )
            added += 1
    conn.commit()
    conn.close()
    return {"ok": True, "count": added}


@app.get("/api/export/vault")
def export_vault(x_vault_token: str = Header(None)):
    """导出隐私库为加密备份（用当前主密码加密）。"""
    f = _vault_fernet(x_vault_token)
    conn = get_db()
    rows = conn.execute("SELECT title, username, password, notes FROM vault ORDER BY id").fetchall()
    conn.close()
    items = []
    for r in rows:
        items.append({
            "title": f.decrypt(r["title"].encode()).decode(),
            "username": f.decrypt(r["username"].encode()).decode(),
            "password": f.decrypt(r["password"].encode()).decode(),
            "notes": f.decrypt(r["notes"].encode()).decode(),
        })
    payload = json.dumps(items, ensure_ascii=False)
    blob = f.encrypt(payload.encode("utf-8")).decode("utf-8")
    return {"data": blob, "count": len(items)}


@app.post("/api/import/vault")
def import_vault(v: VaultImport):
    """导入隐私库加密备份：用备份密码解密，再用当前密钥重新加密写入。"""
    cur_key = app.state.vault_key
    if cur_key is None:
        raise HTTPException(status_code=401, detail="请先解锁隐私库")
    salt_b64 = get_vault_meta("salt")
    if not salt_b64:
        raise HTTPException(status_code=400, detail="尚未设置主密码")
    salt = base64.b64decode(salt_b64)
    key = derive_key(v.password, salt)
    try:
        payload = Fernet(key).decrypt(v.data.encode("utf-8"))
        items = json.loads(payload.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=401, detail="备份密码错误或文件损坏")
    conn = get_db()
    cur_f = Fernet(cur_key)
    added = 0
    for item in items:
        conn.execute(
            "INSERT INTO vault (title, username, password, notes) VALUES (?, ?, ?, ?)",
            (
                cur_f.encrypt(str(item.get("title", "")).encode()).decode(),
                cur_f.encrypt(str(item.get("username", "")).encode()).decode(),
                cur_f.encrypt(str(item.get("password", "")).encode()).decode(),
                cur_f.encrypt(str(item.get("notes", "")).encode()).decode(),
            ),
        )
        added += 1
    conn.commit()
    conn.close()
    return {"ok": True, "count": added}


# ============ 退出 / 静态 / 首页 ============

@app.post("/api/heartbeat")
def heartbeat():
    """前端心跳：每 15 秒一次，用于判断页面是否还开着。"""
    app.state.last_heartbeat = time.time()
    return {"ok": True}


def _kill_edge_window() -> None:
    """关闭本程序打开的 Edge 独立窗口（按配置目录匹配，不误杀用户其它 Edge 窗口）。"""
    try:
        if os.name != "nt":
            return
        ps = (
            "Get-CimInstance Win32_Process -Filter \"name='msedge.exe'\" | "
            "Where-Object { $_.CommandLine -like '*edge_profile*' } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=6,
        )
    except Exception:
        pass


@app.post("/api/shutdown")
def shutdown():
    """退出程序（供无控制台窗口的 exe 使用）：先返回响应，再关闭窗口并退出。"""
    def _exit() -> None:
        time.sleep(0.3)
        _kill_edge_window()
        os._exit(0)

    threading.Thread(target=_exit, daemon=True).start()
    return {"ok": True}


@app.get("/static/{filename}")
def serve_static(filename: str):
    """提供 static 目录下的静态文件（markdown 渲染库等，离线）。"""
    base = STATIC_DIR.resolve()
    target = (STATIC_DIR / filename).resolve()
    # 只允许访问 static 目录内的文件，防路径穿越
    if base not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(target)


@app.get("/")
def index():
    """访问根路径时，返回前端页面。"""
    return FileResponse(STATIC_DIR / "index.html")
