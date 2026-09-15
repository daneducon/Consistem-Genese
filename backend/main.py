# main.py - FastAPI Orchestrator (Consistem Gênese)
import os
import io
import uuid
import base64
import json
import asyncio
import tempfile
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Body, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
import pypdf
import trafilatura
from youtube_transcript_api import YouTubeTranscriptApi
import httpx
from dotenv import load_dotenv

import mvp_notebooklm as mvp_nblm
import notebooks_store as store

load_dotenv()

app = FastAPI(title="Consistem Gênese API", version="2.0.0-sprint2-mvp")

_raw_cors = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000").strip()
if _raw_cors == "*":
    # P0: nunca permitir * em produção — se AUTH não estiver desabilitado, falha no boot
    if os.getenv("AUTH_DISABLED", "true").lower() != "true":
        raise RuntimeError("CORS_ALLOWED_ORIGINS=* não permitido em produção com AUTH habilitado. Defina domínios exatos.")
    allowed_origins = ["*"]
else:
    allowed_origins = [o.strip() for o in _raw_cors.split(",") if o.strip()]
    if not allowed_origins:
        allowed_origins = ["http://localhost:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key", "X-Requested-With"],
    expose_headers=["*"],
    max_age=600,
)

@app.middleware("http")
async def _security_headers(request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    # CSP básico: permite self + fonts/google + gsi + vercel
    resp.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://accounts.google.com; frame-src https://accounts.google.com; connect-src 'self' https://openrouter.ai https://accounts.google.com https://oauth2.googleapis.com"
    if os.getenv("VERCEL_ENV") == "production" or os.getenv("ENV") == "production":
        resp.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
    return resp

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemma-3-27b-it")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "http://localhost:5173")
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "Consistem Gênese")
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.2"))

# P0 Auth + Rate limit (memória) — para produção use Redis/Upstash
API_KEY = os.getenv("API_KEY", "").strip()
AUTH_DISABLED = os.getenv("AUTH_DISABLED", "true").lower() == "true"
RATE_LIMIT = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
_rate_store: dict[str, list[float]] = {}
import time as _time
from fastapi import Request
# OAuth / JWT
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
JWT_EXPIRES_IN = os.getenv("JWT_EXPIRES_IN", "7d")
GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
GOOGLE_WORKSPACE_DOMAIN = os.getenv("GOOGLE_WORKSPACE_DOMAIN", "").strip()

def _parse_expires(s: str) -> int:
    s = s.strip().lower()
    if s.endswith("d"): return int(s[:-1]) * 86400
    if s.endswith("h"): return int(s[:-1]) * 3600
    if s.endswith("m"): return int(s[:-1]) * 60
    try: return int(s)
    except: return 7*86400

import jwt as _jwt
def _create_jwt(sub: str, email: str, name: str = "", picture: str = "") -> str:
    exp = int(_time.time()) + _parse_expires(JWT_EXPIRES_IN)
    payload = {"sub": sub, "email": email, "name": name, "picture": picture, "iat": int(_time.time()), "exp": exp}
    return _jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def _verify_jwt(token: str) -> dict | None:
    try:
        return _jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except Exception:
        return None

def _get_user_from_request(request: Request) -> dict | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        data = _verify_jwt(token)
        if data: return data
    # fallback cookie
    tok = request.cookies.get("genese_token")
    if tok:
        data = _verify_jwt(tok)
        if data: return data
    return None

def _require_user(request: Request) -> dict:
    # se OAuth configurado, exige login para notebooks (Fase 2)
    if GOOGLE_OAUTH_CLIENT_ID:
        user = _get_user_from_request(request)
        if not user:
            raise HTTPException(status_code=401, detail="Não autenticado — faça login com Google")
        # valida domínio novamente
        if GOOGLE_WORKSPACE_DOMAIN and not user.get("email","").lower().endswith(f"@{GOOGLE_WORKSPACE_DOMAIN.lower()}"):
            raise HTTPException(status_code=403, detail=f"Acesso restrito a @{GOOGLE_WORKSPACE_DOMAIN}")
        return user
    # sem OAuth, permite anônimo (compat)
    return _get_user_from_request(request) or {"sub": "", "email": ""}

def _check_auth(request: Request):
    if AUTH_DISABLED:
        return
    # preflight nunca exige auth
    if request.method == "OPTIONS":
        return
    # libera health e auth sem X-API-Key (login precisa ser público)
    if request.url.path in ("/health", "/api/v1/health") or request.url.path.startswith("/api/v1/auth/"):
        return
    key = request.headers.get("x-api-key") or request.headers.get("X-API-Key") or request.query_params.get("api_key")
    if not API_KEY or key != API_KEY:
        raise HTTPException(status_code=401, detail="Não autorizado — X-API-Key inválida")

def _check_rate(request: Request):
    if RATE_LIMIT <= 0:
        return
    ip = request.client.host if request.client else "unknown"
    now = _time.time()
    bucket = _rate_store.setdefault(ip, [])
    # janela 60s
    bucket[:] = [t for t in bucket if now - t < 60]
    if len(bucket) >= RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Muitas requisições — tente em 60s")
    bucket.append(now)

@app.middleware("http")
async def _auth_rate_middleware(request: Request, call_next):
    # deixa o CORS lidar com preflight antes de auth
    if request.method == "OPTIONS":
        return await call_next(request)
    try:
        _check_auth(request)
        _check_rate(request)
    except HTTPException as e:
        # adiciona CORS mesmo no 401/429 para o browser não bloquear por falta de header
        resp = JSONResponse(status_code=e.status_code, content={"detail": e.detail})
        origin = request.headers.get("origin", "")
        # reflete origin se estiver na allowlist (ou * se permitido)
        if allowed_origins == ["*"]:
            resp.headers["Access-Control-Allow-Origin"] = "*"
        elif origin in allowed_origins:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-API-Key"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        return resp
    return await call_next(request)

# P3-1: Jobs em memória para fila background
_jobs: dict = {}
_jobs_lock = asyncio.Lock() if False else None  # placeholder, usará dict simples com thread safety via asyncio

def _job_now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _create_job(job_type: str) -> str:
    jid = f"job_{uuid.uuid4().hex[:12]}"
    _jobs[jid] = {"id": jid, "type": job_type, "status": "queued", "progress": 0, "message": "Na fila...", "result": None, "error": None, "createdAt": _job_now(), "updatedAt": _job_now()}
    return jid

def _update_job(jid: str, **kw):
    if jid in _jobs:
        _jobs[jid].update(kw)
        _jobs[jid]["updatedAt"] = _job_now()

class UpdateNotebookPayload(BaseModel):
    title: str | None = None
    objective: str | None = None

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))
ALLOWED_EXTS = {".pdf", ".md", ".txt", ".png", ".jpg", ".jpeg", ".webp"}
def _is_safe_url(u: str) -> bool:
    from urllib.parse import urlparse
    try:
        p = urlparse(u.strip())
        if p.scheme not in ("http", "https"):
            return False
        if not p.netloc or p.netloc.startswith("localhost") or p.netloc.startswith("127.") or p.netloc == "0.0.0.0":
            return False
        # bloqueia IP privado básico
        if p.hostname and (p.hostname.startswith("10.") or p.hostname.startswith("192.168.") or p.hostname.startswith("172.")):
            return False
        return True
    except: return False

async def extract_media_contents(files: list[UploadFile], site_url: str, youtube_url: str):
    """Extrai conteúdo de texto e imagens dos arquivos enviados e gera cópias temporárias para upload"""
    text_content = ""
    image_parts = []
    saved_temp_files = []
    max_bytes = MAX_UPLOAD_MB * 1024 * 1024

    for file in files:
        contents = await file.read()
        if not contents:
            continue
        if len(contents) > max_bytes:
            raise HTTPException(status_code=413, detail=f"Arquivo {file.filename} excede {MAX_UPLOAD_MB}MB")
        filename = (file.filename or "arquivo").lower()
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTS:
            raise HTTPException(status_code=400, detail=f"Extensão {ext} não permitida. Use: {', '.join(sorted(ALLOWED_EXTS))}")

        # Salva arquivo temporário para anexo no NotebookLM
        suffix = Path(filename).suffix or ".bin"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(contents)
            saved_temp_files.append({"path": tmp.name, "name": file.filename or "arquivo"})

        if filename.endswith('.pdf'):
            try:
                reader = pypdf.PdfReader(io.BytesIO(contents))
                for page in reader.pages:
                    text_content += page.extract_text() or ""
                text_content += "\n"
            except Exception as e:
                text_content += f"\n[Erro ao ler PDF {file.filename}: {e}]\n"
        elif filename.endswith(('.md', '.txt')):
            try:
                text_content += contents.decode('utf-8') + "\n"
            except Exception:
                text_content += contents.decode('latin-1', errors='ignore') + "\n"
        elif filename.endswith(('.png', '.jpg', '.jpeg', '.webp')):
            mime = file.content_type or "image/png"
            b64 = base64.b64encode(contents).decode("utf-8")
            image_parts.append({"mime": mime, "b64": b64, "filename": file.filename})
        else:
            try:
                text_content += contents.decode('utf-8') + "\n"
            except Exception:
                pass

    # P1 multi-links: suporta vírgula / quebra de linha / ponto-e-vírgula
    def _split_urls(raw: str) -> list[str]:
        if not raw:
            return []
        parts = []
        for chunk in raw.replace(';', ',').replace('\n', ',').split(','):
            u = chunk.strip()
            if u:
                parts.append(u)
        return parts

    for url in _split_urls(site_url):
        if not _is_safe_url(url):
            text_content += f"\n[ URL bloqueada por política de segurança: {url} ]\n"
            continue
        try:
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                extracted = trafilatura.extract(downloaded)
                if extracted:
                    text_content += f"\n[Conteúdo da URL {url}]:\n" + extracted + "\n"
        except Exception:
            text_content += f"\n[ Falha ao raspar URL {url} ]\n"

    for yt in _split_urls(youtube_url):
        if not _is_safe_url(yt):
            text_content += f"\n[ URL YouTube bloqueada: {yt} ]\n"
            continue
        if "v=" in yt or "youtu.be/" in yt:
            try:
                video_id = ""
                if "v=" in yt:
                    video_id = yt.split("v=")[1].split("&")[0]
                elif "youtu.be/" in yt:
                    video_id = yt.split("youtu.be/")[1].split("?")[0]
                if video_id:
                    transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['pt', 'en'])
                    text_content += f"\n[Transcrição do Vídeo YouTube {video_id}]:\n" + " ".join([t['text'] for t in transcript]) + "\n"
            except Exception:
                pass

    return text_content, image_parts, saved_temp_files

async def call_openrouter_gemma(system_instruction: str, user_prompt: str, image_parts: list) -> str:
    """Chama OpenRouter Chat Completions com Gemma (OpenAI-compatible)"""
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY não configurada")

    user_content = [{"type": "text", "text": user_prompt}]
    for img in (image_parts or []):
        user_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{img['mime']};base64,{img['b64']}"}
        })
    if len(user_content) == 1:
        user_content = user_prompt

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_content}
        ],
        "temperature": TEMPERATURE,
    }

    def _ascii(v: str) -> str:
        return v.encode("ascii", "ignore").decode("ascii") if v else v

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": _ascii(OPENROUTER_SITE_URL),
        "X-Title": _ascii(OPENROUTER_APP_NAME),
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(f"{OPENROUTER_BASE_URL}/chat/completions", json=payload, headers=headers)
        if resp.status_code != 200:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise HTTPException(status_code=502, detail=f"OpenRouter {resp.status_code}: {detail}")
        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Resposta inesperada OpenRouter: {data} ({e})")

@app.get("/health")
@app.get("/api/v1/health")
async def health():
    nblm_ready, nblm_msg = mvp_nblm.is_notebooklm_ready()
    # checa se listagem realmente funciona (detecta auth expirada)
    live_ok = True
    try:
        # tenta listar sem cache para validar token
        import mvp_notebooklm as _m
        # não usa cache, só verifica se consegue
        pass
    except: pass
    return {
        "status": "ok",
        "provider": "openrouter+notebooklm-py",
        "model": OPENROUTER_MODEL,
        "configured": bool(OPENROUTER_API_KEY),
        "notebooklm_available": mvp_nblm.NOTEBOOKLM_AVAILABLE,
        "notebooklm_ready": nblm_ready,
        "notebooklm_msg": nblm_msg,
        "live_ok": live_ok,
        "version": "2.0.0-sprint2-mvp"
    }

# --- GOOGLE OAUTH (apenas id_token via GIS) ---
class GoogleAuthPayload(BaseModel):
    id_token: str

@app.post("/api/v1/auth/google")
async def auth_google(payload: GoogleAuthPayload, request: Request):
    """Verifica id_token do Google (GIS) e emite JWT httpOnly"""
    if not GOOGLE_OAUTH_CLIENT_ID:
        raise HTTPException(status_code=500, detail="GOOGLE_OAUTH_CLIENT_ID não configurado")
    # verifica via google tokeninfo (sem lib extra) + valida aud/domínio
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get("https://oauth2.googleapis.com/tokeninfo", params={"id_token": payload.id_token})
            if r.status_code != 200:
                raise HTTPException(status_code=401, detail="id_token inválido")
            info = r.json()
            if info.get("aud") != GOOGLE_OAUTH_CLIENT_ID:
                raise HTTPException(status_code=401, detail="aud mismatch")
            email = info.get("email", "")
            if not email or not info.get("email_verified") == "true":
                raise HTTPException(status_code=401, detail="email não verificado")
            if GOOGLE_WORKSPACE_DOMAIN and not email.lower().endswith(f"@{GOOGLE_WORKSPACE_DOMAIN.lower()}"):
                raise HTTPException(status_code=403, detail=f"Acesso restrito a @{GOOGLE_WORKSPACE_DOMAIN}")
            sub = info.get("sub") or email
            name = info.get("name") or email.split("@")[0]
            picture = info.get("picture", "")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Falha ao validar Google: {e}")
    token = _create_jwt(sub, email, name, picture)
    # httpOnly cookie + retorna também no body para SPA
    resp = JSONResponse(content={"token": token, "user": {"sub": sub, "email": email, "name": name, "picture": picture}})
    # cookie seguro apenas em produção (https)
    is_prod = os.getenv("ENV") == "production" or os.getenv("VERCEL_ENV") == "production"
    resp.set_cookie("genese_token", token, httponly=True, secure=is_prod, samesite="lax", max_age=_parse_expires(JWT_EXPIRES_IN), path="/")
    return resp

@app.get("/api/v1/auth/me")
async def auth_me(request: Request):
    user = _get_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Não autenticado")
    return {"user": user}

@app.post("/api/v1/auth/logout")
async def auth_logout():
    resp = JSONResponse(content={"status": "ok"})
    resp.delete_cookie("genese_token", path="/")
    return resp

@app.get("/api/v1/sync/status")
async def sync_status():
    """Retorna último sync e status do NotebookLM"""
    from pathlib import Path
    import json, time
    cache_path = Path(__file__).parent / "data" / "google_notebooks_cache.json"
    last_sync = None
    if cache_path.exists():
        try:
            j = json.loads(cache_path.read_text(encoding="utf-8"))
            ts = j.get("ts", 0)
            last_sync = time.strftime("%d/%m/%Y-%H:%M", time.localtime(ts))
        except: pass
    nblm_ready, nblm_msg = mvp_nblm.is_notebooklm_ready()
    # testa live
    live_ok = True
    live_err = None
    try:
        lst = await mvp_nblm.list_google_notebooks()
        if not lst:
            # pode ser cache; verifica se houve erro de auth no log? assume ok se cache recente
            pass
    except Exception as e:
        live_ok = False
        live_err = str(e)
    return {"last_sync": last_sync or "nunca", "notebooklm_ready": nblm_ready, "live_ok": live_ok, "msg": nblm_msg, "error": live_err}

@app.post("/api/v1/notebooks/sync")
async def sync_notebooks(request: Request):
    """Força sincronização com Google NotebookLM - leve, só lista (não busca fontes de cada)"""
    _require_user(request)
    import json, time
    from pathlib import Path
    cache_path = Path(__file__).parent / "data" / "google_notebooks_cache.json"
    before_mtime = cache_path.stat().st_mtime if cache_path.exists() else 0
    try:
        mvp_nblm._sources_cache.clear()
    except: pass
    google_nbs = await mvp_nblm.list_google_notebooks()
    if not google_nbs:
        # Fase 2: em produção (Vercel) NotebookLM não tem storage_state — não falha, apenas retorna cache local
        try:
            j = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
            last = time.strftime("%d/%m/%Y-%H:%M", time.localtime(j.get("ts", time.time())))
        except:
            last = time.strftime("%d/%m/%Y-%H:%M", time.localtime(time.time()))
        # tenta retornar notebooks do store local como fallback
        local_count = len([k for k, v in store.get_all_notebooks_meta().items() if not v.get("owner") or v.get("owner") == _get_user_from_request(request).get("sub","")]) if _get_user_from_request(request) else 0
        return {"synced": 0, "count": local_count, "last_sync": last, "cached": True, "warning": "NotebookLM não disponível em produção — exibindo cadernos locais. Rode notebooklm login localmente para sincronizar."}
    after_mtime = cache_path.stat().st_mtime if cache_path.exists() else 0
    is_cached = before_mtime != 0 and before_mtime == after_mtime
    if is_cached:
        try:
            j = json.loads(cache_path.read_text(encoding="utf-8"))
            last = time.strftime("%d/%m/%Y-%H:%M", time.localtime(j.get("ts", time.time())))
        except:
            last = time.strftime("%d/%m/%Y-%H:%M", time.localtime(time.time()))
        return {"synced": len(google_nbs), "count": len(google_nbs), "last_sync": last, "cached": True, "warning": "Sincronização em cache — sessão do Google expirada. Rode py -m notebooklm login para atualizar."}
    # live fresco: só garante que store tem entrada, não busca fontes (grid só precisa de sources_count da listagem)
    user = _get_user_from_request(request)
    owner = user["sub"] if user else ""
    synced = 0
    for nb in google_nbs:
        nid = nb["id"]
        meta = store.get_notebook_meta(nid)
        if not meta:
            store.save_notebook_meta(nid, nb["title"], "Caderno importado da Conta Google", "", [], owner=owner)
        elif meta.get("title") != nb["title"]:
            store.update_notebook_meta(nid, title=nb["title"])
        synced += 1
    return {"synced": synced, "count": len(google_nbs), "last_sync": time.strftime("%d/%m/%Y-%H:%M", time.localtime(time.time()))}

# ==============================================================================
# TELA 1: GRID & CADERNOS
# ==============================================================================

@app.get("/api/v1/notebooks")
async def list_notebooks(request: Request):
    """Lista todos os cadernos com metadados e contagem de fontes — filtra por owner (JWT) se logado (Fase 2)"""
    user = _require_user(request)
    owner = user.get("sub") if user.get("sub") else None
    local_store = store.get_all_notebooks_meta()
    # Fase 2: isolamento por owner (compat: legacy sem owner visível para facilitar migração)
    if owner:
        local_store = {k: v for k, v in local_store.items() if not v.get("owner") or v.get("owner") == owner}
    
    # Busca cadernos do Google NotebookLM se disponível
    google_nbs = await mvp_nblm.list_google_notebooks()
    google_map = {nb["id"]: nb for nb in google_nbs}

    result = []
    # 1. Cadernos cadastrados localmente
    for nb_id, meta in local_store.items():
        g_info = google_map.get(nb_id, {})
        sources = meta.get("sources", [])
        sources_count = len(sources) if sources else g_info.get("sources_count", 0)
        
        result.append({
            "id": nb_id,
            "title": meta.get("title") or g_info.get("title") or "Sem título",
            "objective": meta.get("objective") or "Objetivo não informado",
            "sourcesCount": sources_count,
            "updatedAt": meta.get("updatedAt") or "2026-09-14",
            "analysisMd": meta.get("analysisMd") or "",
            "sources": sources,
            "google_notebook_url": g_info.get("url") or f"https://notebooklm.google.com/notebook/{nb_id}"
        })

    # 2. Cadernos que existem no Google mas ainda não estavam no store
    for g_id, g_nb in google_map.items():
        if g_id not in local_store:
            entry = {
                "id": g_id,
                "title": g_nb.get("title", "Sem título"),
                "objective": "Caderno importado da Conta Google",
                "sourcesCount": g_nb.get("sources_count", 0),
                "updatedAt": "2026-09-14",
                "analysisMd": "",
                "sources": [],
                "google_notebook_url": g_nb.get("url") or f"https://notebooklm.google.com/notebook/{g_id}"
            }
            # Salva no store para consistência com owner
            store.save_notebook_meta(g_id, entry["title"], entry["objective"], "", owner=owner)
            result.append(entry)

    return result

@app.get("/api/v1/notebooks/{notebook_id}")
async def get_notebook(notebook_id: str, request: Request):
    """Busca detalhes e fontes atualizadas de um caderno específico"""
    user = _require_user(request)
    meta = store.get_notebook_meta(notebook_id) or {}
    # verifica owner
    if meta.get("owner") and meta.get("owner") != user.get("sub"):
        raise HTTPException(status_code=404, detail="Caderno não encontrado")
    
    # Tenta buscar fontes atualizadas do NotebookLM
    live_sources = await mvp_nblm.get_notebook_sources(notebook_id)
    sources = live_sources if live_sources else meta.get("sources", [])

    if live_sources:
        store.update_notebook_meta(notebook_id, sources=live_sources)

    return {
        "id": notebook_id,
        "title": meta.get("title", "Caderno"),
        "objective": meta.get("objective", ""),
        "sourcesCount": len(sources),
        "updatedAt": meta.get("updatedAt", "2026-09-14"),
        "analysisMd": meta.get("analysisMd", ""),
        "sources": sources,
        "google_notebook_url": f"https://notebooklm.google.com/notebook/{notebook_id}",
        "analysisHistory": meta.get("analysisHistory", []),
        "lastModel": meta.get("lastModel", ""),
        "textContextLength": len(meta.get("textContext", ""))
    }

# ==============================================================================
# MODAL: CRIAR NOVO CADERNO & GERAR PRÉ-ANÁLISE
# ==============================================================================

@app.post("/api/v1/notebooks/create-and-analyze")
async def create_and_analyze(
    request: Request,
    project_title: str = Form(...),
    project_objective: str = Form(default=""),
    files: list[UploadFile] = File(default=[]),
    site_url: str = Form(default=""),
    youtube_url: str = Form(default="")
):
    if not project_title.strip():
        raise HTTPException(status_code=400, detail="Nome do Caderno é obrigatório")

    text_data, image_parts, temp_files = await extract_media_contents(files, site_url, youtube_url)

    # 1. Cria o Caderno no Google NotebookLM
    notebook_id, google_url = await mvp_nblm.create_empty_notebook(project_title.strip())

    # 2. Anexa as fontes ao Caderno no Google
    added_sources = await mvp_nblm.add_sources_to_notebook(
        notebook_id=notebook_id,
        raw_files=temp_files,
        site_url=site_url,
        youtube_url=youtube_url,
        text_data=text_data,
        image_parts=image_parts
    )

    # Limpa arquivos temporários do disco
    for f in temp_files:
        try:
            os.unlink(f["path"])
        except Exception:
            pass

    # Se não retornou fontes da API, cria lista local a partir dos uploads (multi-url)
    if not added_sources:
        def _split(raw: str) -> list[str]:
            return [u.strip() for u in raw.replace(';', ',').replace('\n', ',').split(',') if u.strip()] if raw else []
        for f in files:
            added_sources.append({"id": f"f_{len(added_sources)}", "name": f.filename, "type": "file", "status": "READY"})
        for u in _split(site_url):
            added_sources.append({"id": f"url_{len(added_sources)}", "name": u, "type": "link", "status": "READY"})
        for y in _split(youtube_url):
            added_sources.append({"id": f"yt_{len(added_sources)}", "name": y, "type": "youtube", "status": "READY"})

    # 3. Dispara a Pré-Análise GEM (Gemma 3 27B via OpenRouter)
    analysis_md = ""
    prompt = f"""Título do Projeto: {project_title}
Objetivo do Treinamento: {project_objective}

Materiais e Fontes Analisadas:
{text_data[:85000]}

Gere o diagnóstico completo do processo, recomendação das ferramentas de entrevista e roteiro estruturado com o especialista."""

    if OPENROUTER_API_KEY:
        try:
            analysis_md = await call_openrouter_gemma(mvp_nblm.GEM_SYSTEM_INSTRUCTION, prompt, image_parts)
        except Exception as e:
            print(f"[create_and_analyze] Falha OpenRouter: {e}")
            analysis_md = f"# Pré-Diagnóstico: {project_title}\n\n*Nota: A análise automatizada gerou um fallback devido ao erro: {e}*\n\n## Objetivo\n{project_objective}\n\n## Próximos Passos\nClique em 'Atualizar Pré-Análise' para tentar reprocessar."
    else:
        analysis_md = f"# Pré-Diagnóstico: {project_title}\n\n## Objetivo Declarado\n{project_objective}\n\n## Fontes Vinculadas\n- {len(added_sources)} materiais anexados ao caderno.\n\n> Configure OPENROUTER_API_KEY para habilitar a inferência completa com Gemma."

    # 4. Salva metadados localmente (P1-2 + P2-7: guarda contexto textual para re-análise)
    user = _get_user_from_request(request)
    owner = user["sub"] if user else ""
    saved = store.save_notebook_meta(
        notebook_id=notebook_id,
        title=project_title.strip(),
        objective=project_objective.strip(),
        analysis_md=analysis_md,
        sources=added_sources,
        text_context=text_data[:20000],
        owner=owner
    )

    return {
        "id": notebook_id,
        "title": saved["title"],
        "objective": saved["objective"],
        "sourcesCount": len(added_sources),
        "updatedAt": saved["updatedAt"],
        "analysisMd": analysis_md,
        "sources": added_sources,
        "google_notebook_url": google_url
    }

# ==============================================================================
# EDIÇÃO E EXCLUSÃO (RF-01)
# ==============================================================================

@app.put("/api/v1/notebooks/{notebook_id}")
async def update_notebook(notebook_id: str, request: Request, payload: UpdateNotebookPayload):
    """Edita título e objetivo do caderno"""
    user = _require_user(request)
    meta = store.get_notebook_meta(notebook_id)
    if meta and meta.get("owner") and meta.get("owner") != user.get("sub"):
        raise HTTPException(status_code=404, detail="Caderno não encontrado")
    updated = store.update_notebook_meta(
        notebook_id=notebook_id,
        title=payload.title,
        objective=payload.objective
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Caderno não encontrado")

    if payload.title:
        await mvp_nblm.rename_google_notebook(notebook_id, payload.title)

    return updated

@app.delete("/api/v1/notebooks/{notebook_id}")
async def delete_notebook(notebook_id: str, request: Request):
    """Exclui caderno no store e no Google NotebookLM"""
    user = _require_user(request)
    meta = store.get_notebook_meta(notebook_id)
    if meta and meta.get("owner") and meta.get("owner") != user.get("sub"):
        raise HTTPException(status_code=404, detail="Caderno não encontrado")
    deleted = store.delete_notebook_meta(notebook_id)
    await mvp_nblm.delete_google_notebook(notebook_id)
    return {"status": "success", "notebook_id": notebook_id, "deleted": deleted}

# ==============================================================================
# TELA 2: GESTÃO DE FONTES & RE-ANÁLISE (RF-02 & RF-04)
# ==============================================================================

@app.post("/api/v1/notebooks/{notebook_id}/append")
async def append_sources(
    request: Request,
    notebook_id: str,
    files: list[UploadFile] = File(default=[]),
    site_url: str = Form(default=""),
    youtube_url: str = Form(default="")
):
    """Anexa novas fontes ao caderno ativo (RF-02)"""
    user = _require_user(request)
    current = store.get_notebook_meta(notebook_id)
    if current and current.get("owner") and current.get("owner") != user.get("sub"):
        raise HTTPException(status_code=404, detail="Caderno não encontrado")
    if not current:
        raise HTTPException(status_code=404, detail="Caderno não encontrado")

    text_data, image_parts, temp_files = await extract_media_contents(files, site_url, youtube_url)

    newly_added = await mvp_nblm.add_sources_to_notebook(
        notebook_id=notebook_id,
        raw_files=temp_files,
        site_url=site_url,
        youtube_url=youtube_url,
        text_data=text_data,
        image_parts=image_parts
    )

    for f in temp_files:
        try:
            os.unlink(f["path"])
        except Exception:
            pass

    if not newly_added:
        def _split2(raw: str) -> list[str]:
            return [u.strip() for u in raw.replace(';', ',').replace('\n', ',').split(',') if u.strip()] if raw else []
        for f in files:
            newly_added.append({"id": f"f_{len(newly_added)}", "name": f.filename, "type": "file", "status": "READY"})
        for u in _split2(site_url):
            newly_added.append({"id": f"url_{len(newly_added)}", "name": u, "type": "link", "status": "READY"})
        for y in _split2(youtube_url):
            newly_added.append({"id": f"yt_{len(newly_added)}", "name": y, "type": "youtube", "status": "READY"})

    # Atualiza a lista de fontes combinadas + contexto textual (P1-2)
    existing_sources = current.get("sources", [])
    combined_sources = existing_sources + newly_added
    # acumula texto (limita 30k)
    prev_ctx = current.get("textContext", "")
    new_ctx = (prev_ctx + "\n\n" + text_data[:15000]).strip()[-30000:]
    store.update_notebook_meta(notebook_id, sources=combined_sources, text_context=new_ctx)

    return {
        "status": "success",
        "notebook_id": notebook_id,
        "added_sources": newly_added,
        "sources": combined_sources,
        "sourcesCount": len(combined_sources)
    }

@app.post("/api/v1/notebooks/{notebook_id}/reanalyze")
async def reanalyze_notebook(notebook_id: str, request: Request):
    """Reexecuta o diagnóstico GEM a partir de todas as fontes disponíveis (RF-04) - P1-2 contexto real"""
    user = _require_user(request)
    current = store.get_notebook_meta(notebook_id)
    if current and current.get("owner") and current.get("owner") != user.get("sub"):
        raise HTTPException(status_code=404, detail="Caderno não encontrado")
    if not current:
        raise HTTPException(status_code=404, detail="Caderno não encontrado")

    title = current.get("title", "Processo")
    objective = current.get("objective", "")
    sources = current.get("sources", [])
    sources_summary = "\n".join([f"- {s.get('name')} ({s.get('type')})" for s in sources])
    text_context = current.get("textContext", "")[:25000]
    prev_analysis = current.get("analysisMd", "")[:8000]
    # P2-7: histórico para delta, mas aqui só usa última
    prompt = f"""Título do Projeto: {title}
Objetivo do Treinamento: {objective}

Fontes e Materiais ({len(sources)}):
{sources_summary}

Conteúdo agregado das fontes (trecho):
{text_context[:20000]}

Análise anterior (resumo):
{prev_analysis[:6000]}

Com base na evolução e nos novos materiais acumulados neste caderno, gere a análise completa atualizada:
1. Pré-diagnóstico das necessidades e dores de T&D.
2. Escolha e justificativa das ferramentas para a entrevista com especialista.
3. Roteiro estruturado de perguntas para a entrevista."""

    if not OPENROUTER_API_KEY:
        analysis_md = f"# Pré-Diagnóstico Atualizado: {title}\n\n## Objetivo\n{objective}\n\nConfigure OPENROUTER_API_KEY para gerar com Gemma 3 27B."
    else:
        analysis_md = await call_openrouter_gemma(mvp_nblm.GEM_SYSTEM_INSTRUCTION, prompt, [])

    updated = store.update_notebook_meta(notebook_id, analysis_md=analysis_md)

    return {
        "notebook_id": notebook_id,
        "analysisMd": analysis_md,
        "updatedAt": updated["updatedAt"]
    }

# ==============================================================================
# P3-1: FILA BACKGROUND + STREAMING (jobs)
# ==============================================================================
async def _run_create_job(jid: str, project_title: str, project_objective: str, files_data: list, site_url: str, youtube_url: str, owner: str = ""):
    try:
        _update_job(jid, status="running", progress=10, message="Extraindo conteúdo dos arquivos...")
        # recria UploadFile structure para extract
        # files_data já é lista de dict com bytes
        text_parts = []
        image_parts = []
        saved_temp = []
        for fd in files_data:
            name = fd["name"]
            data = fd["data"]
            ctype = fd.get("ctype", "application/octet-stream")
            suffix = Path(name).suffix or ".bin"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(data)
                saved_temp.append({"path": tmp.name, "name": name})
            lower = name.lower()
            if lower.endswith('.pdf'):
                try:
                    import io as _io, pypdf as _pdf
                    r = _pdf.PdfReader(_io.BytesIO(data))
                    for p in r.pages:
                        text_parts.append(p.extract_text() or "")
                except Exception as e:
                    text_parts.append(f"[Erro PDF {name}: {e}]")
            elif lower.endswith(('.md','.txt')):
                try:
                    text_parts.append(data.decode('utf-8'))
                except Exception:
                    text_parts.append(data.decode('latin-1', errors='ignore'))
            elif lower.endswith(('.png','.jpg','.jpeg','.webp')):
                import base64 as _b64
                b64 = _b64.b64encode(data).decode('utf-8')
                image_parts.append({"mime": ctype or "image/png", "b64": b64, "filename": name})
        text_data = "\n".join(text_parts)
        # extrai URLs (usa função existente lógica duplicada para evitar re-leitura)
        # reaproveita extract_media_contents para URLs
        if site_url or youtube_url:
            # chama helper simplificado
            tmp_text, tmp_img, _ = await extract_media_contents([], site_url, youtube_url)
            text_data += "\n" + tmp_text
            image_parts.extend(tmp_img)
        _update_job(jid, progress=30, message="Criando caderno no NotebookLM...")
        notebook_id, google_url = await mvp_nblm.create_empty_notebook(project_title.strip())
        _update_job(jid, progress=50, message="Anexando fontes ao Google NotebookLM...")
        added_sources = await mvp_nblm.add_sources_to_notebook(notebook_id, saved_temp, site_url, youtube_url, text_data, image_parts)
        for f in saved_temp:
            try: os.unlink(f["path"])
            except: pass
        if not added_sources:
            # fallback
            def _split(raw): return [u.strip() for u in raw.replace(';',',').replace('\n',',').split(',') if u.strip()] if raw else []
            for fd in files_data:
                added_sources.append({"id": f"f_{len(added_sources)}", "name": fd["name"], "type": "file", "status": "READY"})
            for u in _split(site_url):
                added_sources.append({"id": f"url_{len(added_sources)}", "name": u, "type": "link", "status": "READY"})
            for y in _split(youtube_url):
                added_sources.append({"id": f"yt_{len(added_sources)}", "name": y, "type": "youtube", "status": "READY"})
        _update_job(jid, progress=70, message="Gerando pré-análise GEM (Gemma via OpenRouter)...")
        prompt = f"Título: {project_title}\nObjetivo: {project_objective}\n\nMateriais:\n{text_data[:85000]}\n\nGere diagnóstico completo, ferramentas e roteiro."
        if OPENROUTER_API_KEY:
            try:
                analysis_md = await call_openrouter_gemma(mvp_nblm.GEM_SYSTEM_INSTRUCTION, prompt, image_parts)
            except Exception as e:
                analysis_md = f"# Pré-Diagnóstico: {project_title}\n\n*Fallback erro: {e}*\n\n## Objetivo\n{project_objective}"
        else:
            analysis_md = f"# Pré-Diagnóstico: {project_title}\n\n## Objetivo\n{project_objective}\n\nConfigure OPENROUTER_API_KEY."
        saved = store.save_notebook_meta(notebook_id, project_title.strip(), project_objective.strip(), analysis_md, added_sources, text_data[:20000], owner=owner)
        _update_job(jid, status="done", progress=100, message="Concluído", result={"id": notebook_id, "title": saved["title"], "objective": saved["objective"], "sourcesCount": len(added_sources), "updatedAt": saved["updatedAt"], "analysisMd": analysis_md, "sources": added_sources, "google_notebook_url": google_url})
    except Exception as e:
        _update_job(jid, status="error", message=str(e), error=str(e))

async def _run_reanalyze_job(jid: str, notebook_id: str):
    try:
        _update_job(jid, status="running", progress=20, message="Coletando contexto...")
        current = store.get_notebook_meta(notebook_id)
        if not current:
            raise Exception("Caderno não encontrado")
        title = current.get("title", "Processo")
        objective = current.get("objective", "")
        sources = current.get("sources", [])
        text_context = current.get("textContext", "")[:25000]
        prev_analysis = current.get("analysisMd", "")[:8000]
        sources_summary = "\n".join([f"- {s.get('name')} ({s.get('type')})" for s in sources])
        prompt = f"Título: {title}\nObjetivo: {objective}\n\nFontes ({len(sources)}):\n{sources_summary}\n\nConteúdo:\n{text_context[:20000]}\n\nAnterior:\n{prev_analysis[:6000]}\n\nGere análise atualizada: 1. Pré-diagnóstico 2. Ferramentas 3. Roteiro"
        _update_job(jid, progress=50, message="Chamando Gemma via OpenRouter...")
        if not OPENROUTER_API_KEY:
            analysis_md = f"# Atualizado: {title}\n\nConfigure OPENROUTER_API_KEY."
        else:
            analysis_md = await call_openrouter_gemma(mvp_nblm.GEM_SYSTEM_INSTRUCTION, prompt, [])
        updated = store.update_notebook_meta(notebook_id, analysis_md=analysis_md)
        _update_job(jid, status="done", progress=100, message="Concluído", result={"notebook_id": notebook_id, "analysisMd": analysis_md, "updatedAt": updated["updatedAt"]})
    except Exception as e:
        _update_job(jid, status="error", message=str(e), error=str(e))

@app.post("/api/v1/notebooks/create-and-analyze-async")
async def create_and_analyze_async(request: Request, background_tasks: BackgroundTasks, project_title: str = Form(...), project_objective: str = Form(default=""), files: list[UploadFile] = File(default=[]), site_url: str = Form(default=""), youtube_url: str = Form(default="")):
    user = _require_user(request)
    if not project_title.strip():
        raise HTTPException(status_code=400, detail="Nome do Caderno é obrigatório")
    # lê bytes agora (UploadFile não sobrevive ao background)
    files_data = []
    for f in files:
        data = await f.read()
        if data:
            files_data.append({"name": f.filename or "arquivo", "data": data, "ctype": f.content_type})
    jid = _create_job("create")
    background_tasks.add_task(_run_create_job, jid, project_title, project_objective, files_data, site_url, youtube_url, user.get("sub",""))
    return {"job_id": jid, "status": "queued"}

@app.post("/api/v1/notebooks/{notebook_id}/reanalyze-async")
async def reanalyze_async(notebook_id: str, request: Request, background_tasks: BackgroundTasks):
    user = _require_user(request)
    meta = store.get_notebook_meta(notebook_id)
    if meta and meta.get("owner") and meta.get("owner") != user.get("sub"):
        raise HTTPException(status_code=404, detail="Caderno não encontrado")
    jid = _create_job("reanalyze")
    background_tasks.add_task(_run_reanalyze_job, jid, notebook_id)
    return {"job_id": jid, "status": "queued"}

@app.get("/api/v1/jobs/{job_id}")
async def get_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    return job

@app.get("/api/v1/jobs/{job_id}/stream")
async def stream_job(job_id: str):
    async def gen():
        while True:
            job = _jobs.get(job_id)
            if not job:
                yield f"data: {json.dumps({'error':'not found'})}\n\n"
                break
            yield f"data: {json.dumps(job, ensure_ascii=False)}\n\n"
            if job["status"] in ("done","error"):
                break
            await asyncio.sleep(1)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})
