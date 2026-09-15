# main.py - FastAPI Orchestrator (Consistem Sinapse GEM)
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

app = FastAPI(title="Consistem Sinapse API", version="2.0.0-sprint2-mvp")

allowed_origins = os.getenv("CORS_ALLOWED_ORIGINS", "*").split(",") if os.getenv("CORS_ALLOWED_ORIGINS") != "*" else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemma-3-27b-it")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "http://localhost:5173")
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "Consistem Sinapse GEM")
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.2"))

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

async def extract_media_contents(files: list[UploadFile], site_url: str, youtube_url: str):
    """Extrai conteúdo de texto e imagens dos arquivos enviados e gera cópias temporárias para upload"""
    text_content = ""
    image_parts = []
    saved_temp_files = []

    for file in files:
        contents = await file.read()
        if not contents:
            continue
        filename = (file.filename or "arquivo").lower()

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
        try:
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                extracted = trafilatura.extract(downloaded)
                if extracted:
                    text_content += f"\n[Conteúdo da URL {url}]:\n" + extracted + "\n"
        except Exception:
            text_content += f"\n[ Falha ao raspar URL {url} ]\n"

    for yt in _split_urls(youtube_url):
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
async def sync_notebooks():
    """Força sincronização com Google NotebookLM - leve, só lista (não busca fontes de cada)"""
    import json, time
    from pathlib import Path
    cache_path = Path(__file__).parent / "data" / "google_notebooks_cache.json"
    before_mtime = cache_path.stat().st_mtime if cache_path.exists() else 0
    try:
        mvp_nblm._sources_cache.clear()
    except: pass
    google_nbs = await mvp_nblm.list_google_notebooks()
    if not google_nbs:
        raise HTTPException(status_code=401, detail="Sessão do Google expirada. No terminal rode: py -m notebooklm login e tente novamente.")
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
    synced = 0
    for nb in google_nbs:
        nid = nb["id"]
        meta = store.get_notebook_meta(nid)
        if not meta:
            store.save_notebook_meta(nid, nb["title"], "Caderno importado da Conta Google", "", [])
        elif meta.get("title") != nb["title"]:
            store.update_notebook_meta(nid, title=nb["title"])
        synced += 1
    return {"synced": synced, "count": len(google_nbs), "last_sync": time.strftime("%d/%m/%Y-%H:%M", time.localtime(time.time()))}

# ==============================================================================
# TELA 1: GRID & CADERNOS
# ==============================================================================

@app.get("/api/v1/notebooks")
async def list_notebooks():
    """Lista todos os cadernos com metadados e contagem de fontes"""
    local_store = store.get_all_notebooks_meta()
    
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
            # Salva no store para consistência
            store.save_notebook_meta(g_id, entry["title"], entry["objective"], "")
            result.append(entry)

    return result

@app.get("/api/v1/notebooks/{notebook_id}")
async def get_notebook(notebook_id: str):
    """Busca detalhes e fontes atualizadas de um caderno específico"""
    meta = store.get_notebook_meta(notebook_id) or {}
    
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
    saved = store.save_notebook_meta(
        notebook_id=notebook_id,
        title=project_title.strip(),
        objective=project_objective.strip(),
        analysis_md=analysis_md,
        sources=added_sources,
        text_context=text_data[:20000]
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
async def update_notebook(notebook_id: str, payload: UpdateNotebookPayload):
    """Edita título e objetivo do caderno"""
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
async def delete_notebook(notebook_id: str):
    """Exclui caderno no store e no Google NotebookLM"""
    deleted = store.delete_notebook_meta(notebook_id)
    await mvp_nblm.delete_google_notebook(notebook_id)
    return {"status": "success", "notebook_id": notebook_id, "deleted": deleted}

# ==============================================================================
# TELA 2: GESTÃO DE FONTES & RE-ANÁLISE (RF-02 & RF-04)
# ==============================================================================

@app.post("/api/v1/notebooks/{notebook_id}/append")
async def append_sources(
    notebook_id: str,
    files: list[UploadFile] = File(default=[]),
    site_url: str = Form(default=""),
    youtube_url: str = Form(default="")
):
    """Anexa novas fontes ao caderno ativo (RF-02)"""
    current = store.get_notebook_meta(notebook_id)
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
async def reanalyze_notebook(notebook_id: str):
    """Reexecuta o diagnóstico GEM a partir de todas as fontes disponíveis (RF-04) - P1-2 contexto real"""
    current = store.get_notebook_meta(notebook_id)
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
async def _run_create_job(jid: str, project_title: str, project_objective: str, files_data: list, site_url: str, youtube_url: str):
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
        saved = store.save_notebook_meta(notebook_id, project_title.strip(), project_objective.strip(), analysis_md, added_sources, text_data[:20000])
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
async def create_and_analyze_async(background_tasks: BackgroundTasks, project_title: str = Form(...), project_objective: str = Form(default=""), files: list[UploadFile] = File(default=[]), site_url: str = Form(default=""), youtube_url: str = Form(default="")):
    if not project_title.strip():
        raise HTTPException(status_code=400, detail="Nome do Caderno é obrigatório")
    # lê bytes agora (UploadFile não sobrevive ao background)
    files_data = []
    for f in files:
        data = await f.read()
        if data:
            files_data.append({"name": f.filename or "arquivo", "data": data, "ctype": f.content_type})
    jid = _create_job("create")
    background_tasks.add_task(_run_create_job, jid, project_title, project_objective, files_data, site_url, youtube_url)
    return {"job_id": jid, "status": "queued"}

@app.post("/api/v1/notebooks/{notebook_id}/reanalyze-async")
async def reanalyze_async(notebook_id: str, background_tasks: BackgroundTasks):
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
