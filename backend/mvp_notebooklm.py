# mvp_notebooklm.py — Wrapper NotebookLM-Py para Consistem Gênese
# Lib: https://github.com/teng-lin/notebooklm-py
import os
import tempfile
import asyncio
from pathlib import Path
from datetime import datetime

NOTEBOOKLM_AVAILABLE = False
NOTEBOOKLM_ERROR = None

try:
    from notebooklm import NotebookLMClient  # type: ignore
    from notebooklm.types import SourceStatus  # type: ignore
    NOTEBOOKLM_AVAILABLE = True
except Exception as e:
    NOTEBOOKLM_ERROR = str(e)

USE_NOTEBOOKLM = os.getenv("USE_NOTEBOOKLM", "true").lower() == "true"
# Vercel serverless não tem browser/storage persistente — detecta e opera em modo cache
IS_VERCEL = bool(os.getenv("VERCEL") or os.getenv("VERCEL_ENV"))
NOTEBOOKLM_STORAGE_PATH = os.getenv("NOTEBOOKLM_STORAGE_PATH", "").strip()
NOTEBOOKLM_TIMEOUT_S = float(os.getenv("NOTEBOOKLM_TIMEOUT_S", "9"))

# P1-3: cache simples 30s para sources + retry config
_sources_cache: dict = {}  # notebook_id -> (timestamp, data)
_CACHE_TTL = 30
_RETRY_ATTEMPTS = 3

# Diagnóstico: guarda o último erro live para expor via /sync/status (nunca segredo)
_last_sync_error: str | None = None
_last_sync_error_at: str | None = None

def _record_sync_error(e: Exception) -> str:
    """Resume o erro sem vazar segredo (cookies/tokens)."""
    global _last_sync_error, _last_sync_error_at
    msg = f"{type(e).__name__}: {str(e)[:300]}"
    # corta possível leak de JSON de storage_state
    if len(msg) > 300:
        msg = msg[:300]
    _last_sync_error = msg
    try:
        _last_sync_error_at = datetime.now().strftime("%d/%m/%Y-%H:%M")
    except Exception:
        _last_sync_error_at = None
    return msg

def get_last_sync_error() -> dict:
    return {"error": _last_sync_error, "at": _last_sync_error_at}


def _restore_env_storage_state() -> str | None:
    """Permite injetar storage_state via env (Vercel): NOTEBOOKLM_STORAGE_STATE=base64(json) -> /tmp.

    Além do arquivo plano em /tmp, espelha para
    $NOTEBOOKLM_HOME/profiles/default/storage_state.json e fixa NOTEBOOKLM_HOME,
    porque NotebookLMClient.from_storage() (sem path) resolve pelo HOME/perfil,
    não pelo /tmp avulso. Sem isso o /health diria ready:true mas as chamadas
    live continuariam caindo em cache na Vercel.
    """
    raw = os.getenv("NOTEBOOKLM_STORAGE_STATE", "").strip()
    if not raw:
        return None
    try:
        import base64 as _b64
        import json as _json
        # aceita base64 ou JSON puro
        try:
            decoded = _b64.b64decode(raw).decode("utf-8")
        except Exception:
            decoded = raw
        _json.loads(decoded)  # valida que é JSON
        tmp = Path(tempfile.gettempdir()) / "nblm_storage_state.json"
        tmp.write_text(decoded, encoding="utf-8")
        # espelha para o layout de perfil que o from_storage() enxerga
        try:
            home = Path(os.getenv("NOTEBOOKLM_HOME", "").strip() or (Path(tempfile.gettempdir()) / "nblmhome"))
            prof_dir = home / "profiles" / "default"
            prof_dir.mkdir(parents=True, exist_ok=True)
            (prof_dir / "storage_state.json").write_text(decoded, encoding="utf-8")
            os.environ["NOTEBOOKLM_HOME"] = str(home)
        except Exception as e:
            print(f"[notebooklm] aviso: não espelhou perfil ({e})")
        return str(tmp)
    except Exception as e:
        print(f"[notebooklm] NOTEBOOKLM_STORAGE_STATE inválido: {e}")
        return None


def _storage_path_for_client() -> str | None:
    """Path explícito p/ NotebookLMClient.from_storage(path=...)."""
    if NOTEBOOKLM_STORAGE_PATH and Path(NOTEBOOKLM_STORAGE_PATH).exists():
        return NOTEBOOKLM_STORAGE_PATH
    restored = _restore_env_storage_state()
    if restored and Path(restored).exists():
        return restored
    plat = Path(tempfile.gettempdir()) / "nblm_storage_state.json"
    if plat.exists():
        return str(plat)
    return None


def _client_kwargs() -> dict:
    p = _storage_path_for_client()
    return {"path": p} if p else {}

GEM_SYSTEM_INSTRUCTION = """
Você é o GEM: Analista de Diagnóstico T&D, especialista em mapeamento de necessidades de treinamento e análise de contexto.
Sua tarefa é analisar os materiais brutos fornecidos e gerar:
1. Pré-diagnóstico do contexto atual e lacunas encontradas.
2. Escolha e justificativa das ferramentas para a entrevista (entre: Árvore de problemas, Ishikawa, Matriz CSD, PDCA/MASP, Canvas Empatia, Diagnóstico de competências).
3. Proposta de abordagem e roteiro estruturado de entrevista com o conteudista.
Responda em Markdown bem estruturado em PT-BR.
"""

def is_notebooklm_ready() -> tuple[bool, str]:
    """Checa se lib instalada e auth existe (suporta Vercel via env). Nunca levanta exceção."""
    if not NOTEBOOKLM_AVAILABLE:
        return False, f"lib não instalada: {NOTEBOOKLM_ERROR}"
    if not USE_NOTEBOOKLM:
        return False, "USE_NOTEBOOKLM=false (modo local/cache)"
    # 1. path explícito via env
    if NOTEBOOKLM_STORAGE_PATH and Path(NOTEBOOKLM_STORAGE_PATH).exists():
        return True, f"auth ok (env path): {NOTEBOOKLM_STORAGE_PATH}"
    # 2. storage via env (Vercel) -> restaura em /tmp
    restored = _restore_env_storage_state()
    if restored and Path(restored).exists():
        return True, f"auth ok (env): {restored}"
    candidates = [
        Path(tempfile.gettempdir()) / "nblm_storage_state.json",
        Path.home() / ".notebooklm" / "profiles" / "default" / "storage_state.json",
        Path.home() / ".config" / "notebooklm" / "storage_state.json",
        Path.home() / ".notebooklm" / "storage_state.json",
        Path("./storage_state.json"),
    ]
    for p in candidates:
        try:
            if p.exists():
                return True, f"auth ok: {p}"
        except Exception:
            continue
    if IS_VERCEL:
        return False, "modo cache (Vercel sem storage_state — defina NOTEBOOKLM_STORAGE_STATE ou hospede backend fora da Vercel)"
    return False, "auth não encontrada — rode: notebooklm login"

def google_cache_path() -> Path:
    """Onde fica google_notebooks_cache.json (/tmp na Vercel, que é read-only fora dele)."""
    if IS_VERCEL:
        return Path(tempfile.gettempdir()) / "google_notebooks_cache.json"
    return Path(__file__).parent / "data" / "google_notebooks_cache.json"

def read_notebooks_cache(max_age_s: int = 86400) -> tuple[list, float]:
    """Lê cache de disco sem nunca falhar. Retorna (data, ts)."""
    cache_path = google_cache_path()
    try:
        import json as _json
        import time as _t
        if cache_path.exists():
            j = _json.loads(cache_path.read_text(encoding="utf-8"))
            if _t.time() - j.get("ts", 0) < max_age_s:
                return j.get("data", []), j.get("ts", 0)
    except Exception:
        pass
    return [], 0


async def list_google_notebooks() -> list[dict]:
    """Lista notebooks do Google. Resiliente: timeout curto na Vercel, fallback p/ cache, nunca levanta."""
    cache_path = google_cache_path()
    ready, _msg = is_notebooklm_ready()
    if not ready:
        cached, _ = read_notebooks_cache()
        return cached
    try:
        async def _live():
            async with NotebookLMClient.from_storage(**_client_kwargs()) as client:
                nbs = await client.notebooks.list()
                result = []
                for nb in nbs:
                    nb_id = getattr(nb, 'id', '') or str(nb)
                    nb_title = getattr(nb, 'title', '') or 'Sem título'
                    result.append({
                        "id": nb_id,
                        "title": nb_title,
                        "url": f"https://notebooklm.google.com/notebook/{nb_id}",
                        "sources_count": getattr(nb, 'sources_count', 0) or 0
                    })
                return result
        result = await asyncio.wait_for(_live(), timeout=NOTEBOOKLM_TIMEOUT_S)
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            import json, time
            cache_path.write_text(json.dumps({"ts": time.time(), "data": result}, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        # live ok — limpa último erro
        global _last_sync_error
        _last_sync_error = None
        return result
    except Exception as e:
        _record_sync_error(e)
        print(f"[notebooklm] listagem live falhou (usa cache): {e}")
        cached, _ = read_notebooks_cache()
        return cached

async def get_notebook_sources(notebook_id: str) -> list[dict]:
    """Lista as fontes reais de um caderno e seus status (READY ou INDEXING) - P1-3 com cache 30s + retry"""
    ready, _ = is_notebooklm_ready()
    if not ready:
        return []
    # cache hit
    import time as _time
    cached = _sources_cache.get(notebook_id)
    if cached and (_time.time() - cached[0] < _CACHE_TTL):
        return cached[1]
    last_err = None
    attempts = 1 if IS_VERCEL else _RETRY_ATTEMPTS
    for attempt in range(attempts):
        try:
            async def _live_sources():
                async with NotebookLMClient.from_storage(**_client_kwargs()) as client:
                    return await client.sources.list(notebook_id)
            srcs = await asyncio.wait_for(_live_sources(), timeout=NOTEBOOKLM_TIMEOUT_S)
            formatted = []
            for s in srcs:
                s_id = getattr(s, 'id', '')
                s_title = getattr(s, 'title', '') or 'Fonte'
                s_status = getattr(s, 'status', None)
                status_str = "READY"
                if hasattr(s, 'is_processing') and s.is_processing:
                    status_str = "INDEXING"
                elif str(s_status).upper().find("PROCESS") != -1:
                    status_str = "INDEXING"
                elif str(s_status).upper().find("READY") != -1:
                    status_str = "READY"
                s_type = "file"
                if getattr(s, 'url', None):
                    url = str(s.url)
                    s_type = "youtube" if "youtube.com" in url or "youtu.be" in url else "link"
                formatted.append({
                    "id": s_id,
                    "name": s_title,
                    "type": s_type,
                    "status": status_str,
                    "url": getattr(s, 'url', None)
                })
            _sources_cache[notebook_id] = (_time.time(), formatted)
            return formatted
        except Exception as e:
            last_err = e
            print(f"[notebooklm] tentativa {attempt+1}/{attempts} erro ao listar fontes {notebook_id}: {e}")
            if attempt < attempts - 1:
                await asyncio.sleep(0.5 * (2 ** attempt))
    print(f"[notebooklm] erro ao listar fontes do notebook {notebook_id} após {attempts} tentativas: {last_err}")
    # retorna cache stale se houver
    if cached:
        return cached[1]
    return []

async def create_empty_notebook(title: str) -> tuple[str, str]:
    """Cria um caderno vazio no NotebookLM e retorna (notebook_id, notebook_url)"""
    ready, _ = is_notebooklm_ready()
    if not ready or not USE_NOTEBOOKLM:
        fake_id = f"nb_local_{os.urandom(4).hex()}"
        return fake_id, f"https://notebooklm.google.com/notebook/{fake_id}"
    
    async with NotebookLMClient.from_storage(**_client_kwargs()) as client:
        nb = await client.notebooks.create(title)
        nb_id = nb.id if hasattr(nb, 'id') else (nb.get('id') if isinstance(nb, dict) else str(nb))
        return nb_id, f"https://notebooklm.google.com/notebook/{nb_id}"

async def add_sources_to_notebook(notebook_id: str, raw_files: list = None, site_url: str = "", youtube_url: str = "", text_data: str = "", image_parts: list = None) -> list[dict]:
    """Anexa fontes ao caderno existente e retorna lista de fontes criadas"""
    ready, _ = is_notebooklm_ready()
    if not ready or not USE_NOTEBOOKLM:
        return []
    
    added_list = []
    async with NotebookLMClient.from_storage(**_client_kwargs()) as client:
        # 1. Arquivos brutos
        for f in (raw_files or []):
            try:
                # Se for dict com path
                f_path = f.get("path")
                f_name = f.get("name", "arquivo")
                if f_path and os.path.exists(f_path):
                    await client.sources.add_file(notebook_id, f_path, title=f_name, wait=False)
                    added_list.append({"name": f_name, "type": "file", "status": "INDEXING"})
            except Exception as e:
                print(f"[notebooklm] erro add_file {f}: {e}")

        # 2. Imagens
        import base64
        for idx, img in enumerate(image_parts or []):
            try:
                b64 = img.get("b64")
                if not b64:
                    continue
                data = base64.b64decode(b64)
                img_name = img.get("filename", f"imagem_{idx+1}.png")
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                    tf.write(data)
                    tf_path = tf.name
                try:
                    await client.sources.add_file(notebook_id, tf_path, title=img_name, wait=False)
                    added_list.append({"name": img_name, "type": "image", "status": "INDEXING"})
                finally:
                    try:
                        os.unlink(tf_path)
                    except Exception:
                        pass
            except Exception as e:
                print(f"[notebooklm] erro add imagem: {e}")

        # 3. URL de site (multi)
        def _split(raw: str) -> list[str]:
            if not raw:
                return []
            out=[]
            for chunk in raw.replace(';', ',').replace('\n', ',').split(','):
                u=chunk.strip()
                if u:
                    out.append(u)
            return out
        for url in _split(site_url):
            try:
                await client.sources.add_url(notebook_id, url, wait=False)
                added_list.append({"name": url, "type": "link", "status": "INDEXING"})
            except Exception as e:
                print(f"[notebooklm] erro add_url {url}: {e}")

        # 4. YouTube URL (multi)
        for yurl in _split(youtube_url):
            try:
                await client.sources.add_url(notebook_id, yurl, wait=False)
                added_list.append({"name": yurl, "type": "youtube", "status": "INDEXING"})
            except Exception as e:
                print(f"[notebooklm] erro add youtube {yurl}: {e}")

        # 5. Texto direto
        if text_data and text_data.strip():
            try:
                if hasattr(client.sources, "add_text"):
                    await client.sources.add_text(notebook_id, text_data, wait=False)
                    added_list.append({"name": "Contexto do Treinamento (Texto)", "type": "text", "status": "INDEXING"})
                else:
                    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as tf:
                        tf.write(f"# Contexto\n\n{text_data[:80000]}")
                        tf_path = tf.name
                    try:
                        await client.sources.add_file(notebook_id, tf_path, title="Contexto do Treinamento", wait=False)
                        added_list.append({"name": "Contexto do Treinamento", "type": "file", "status": "INDEXING"})
                    finally:
                        try:
                            os.unlink(tf_path)
                        except Exception:
                            pass
            except Exception as e:
                print(f"[notebooklm] erro add text: {e}")

    # invalida cache para forçar refresh no próximo get
    _sources_cache.pop(notebook_id, None)
    return added_list

async def rename_google_notebook(notebook_id: str, new_title: str) -> bool:
    """Renomeia caderno no NotebookLM"""
    ready, _ = is_notebooklm_ready()
    if not ready or not USE_NOTEBOOKLM:
        return True
    try:
        async with NotebookLMClient.from_storage(**_client_kwargs()) as client:
            await client.notebooks.rename(notebook_id, new_title)
            return True
    except Exception as e:
        print(f"[notebooklm] erro ao renomear: {e}")
        return False

async def delete_google_notebook(notebook_id: str) -> bool:
    """Exclui caderno no NotebookLM"""
    ready, _ = is_notebooklm_ready()
    if not ready or not USE_NOTEBOOKLM:
        return True
    try:
        async with NotebookLMClient.from_storage(**_client_kwargs()) as client:
            await client.notebooks.delete(notebook_id)
            return True
    except Exception as e:
        print(f"[notebooklm] erro ao excluir: {e}")
        return False
