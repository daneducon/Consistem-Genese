# mvp_notebooklm.py — Wrapper NotebookLM-Py para Consistem Sinapse
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

# P1-3: cache simples 30s para sources + retry config
_sources_cache: dict = {}  # notebook_id -> (timestamp, data)
_CACHE_TTL = 30
_RETRY_ATTEMPTS = 3

GEM_SYSTEM_INSTRUCTION = """
Você é o GEM: Analista de Diagnóstico T&D, especialista em mapeamento de necessidades de treinamento e análise de contexto.
Sua tarefa é analisar os materiais brutos fornecidos e gerar:
1. Pré-diagnóstico do contexto atual e lacunas encontradas.
2. Escolha e justificativa das ferramentas para a entrevista (entre: Árvore de problemas, Ishikawa, Matriz CSD, PDCA/MASP, Canvas Empatia, Diagnóstico de competências).
3. Proposta de abordagem e roteiro estruturado de entrevista com o conteudista.
Responda em Markdown bem estruturado em PT-BR.
"""

def is_notebooklm_ready() -> tuple[bool, str]:
    """Checa se lib instalada e auth existe"""
    if not NOTEBOOKLM_AVAILABLE:
        return False, f"lib não instalada: {NOTEBOOKLM_ERROR}"
    candidates = [
        Path.home() / ".notebooklm" / "profiles" / "default" / "storage_state.json",
        Path.home() / ".config" / "notebooklm" / "storage_state.json",
        Path.home() / ".notebooklm" / "storage_state.json",
        Path("./storage_state.json"),
    ]
    for p in candidates:
        if p.exists():
            return True, f"auth ok: {p}"
    return False, "auth não encontrada — rode: notebooklm login"

async def list_google_notebooks() -> list[dict]:
    """Lista todos os notebooks da conta Google - com cache em disco para auth expirada"""
    ready, _ = is_notebooklm_ready()
    if not ready or not USE_NOTEBOOKLM:
        return []
    cache_path = Path(__file__).parent / "data" / "google_notebooks_cache.json"
    try:
        async with NotebookLMClient.from_storage() as client:
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
            # salva cache
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                import json, time
                cache_path.write_text(json.dumps({"ts": time.time(), "data": result}, ensure_ascii=False), encoding="utf-8")
            except: pass
            return result
    except Exception as e:
        print(f"[notebooklm] erro ao listar notebooks: {e}")
        # tenta cache
        try:
            import json, time
            if cache_path.exists():
                j = json.loads(cache_path.read_text(encoding="utf-8"))
                if time.time() - j.get("ts", 0) < 86400:
                    print("[notebooklm] usando cache de notebooks")
                    return j.get("data", [])
        except: pass
        return []

async def get_notebook_sources(notebook_id: str) -> list[dict]:
    """Lista as fontes reais de um caderno e seus status (READY ou INDEXING) - P1-3 com cache 30s + retry"""
    ready, _ = is_notebooklm_ready()
    if not ready or not USE_NOTEBOOKLM:
        return []
    # cache hit
    import time as _time
    cached = _sources_cache.get(notebook_id)
    if cached and (_time.time() - cached[0] < _CACHE_TTL):
        return cached[1]
    last_err = None
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            async with NotebookLMClient.from_storage() as client:
                srcs = await client.sources.list(notebook_id)
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
            print(f"[notebooklm] tentativa {attempt+1}/{_RETRY_ATTEMPTS} erro ao listar fontes {notebook_id}: {e}")
            if attempt < _RETRY_ATTEMPTS - 1:
                await asyncio.sleep(0.5 * (2 ** attempt))
    print(f"[notebooklm] erro ao listar fontes do notebook {notebook_id} após {_RETRY_ATTEMPTS} tentativas: {last_err}")
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
    
    async with NotebookLMClient.from_storage() as client:
        nb = await client.notebooks.create(title)
        nb_id = nb.id if hasattr(nb, 'id') else (nb.get('id') if isinstance(nb, dict) else str(nb))
        return nb_id, f"https://notebooklm.google.com/notebook/{nb_id}"

async def add_sources_to_notebook(notebook_id: str, raw_files: list = None, site_url: str = "", youtube_url: str = "", text_data: str = "", image_parts: list = None) -> list[dict]:
    """Anexa fontes ao caderno existente e retorna lista de fontes criadas"""
    ready, _ = is_notebooklm_ready()
    if not ready or not USE_NOTEBOOKLM:
        return []
    
    added_list = []
    async with NotebookLMClient.from_storage() as client:
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
        async with NotebookLMClient.from_storage() as client:
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
        async with NotebookLMClient.from_storage() as client:
            await client.notebooks.delete(notebook_id)
            return True
    except Exception as e:
        print(f"[notebooklm] erro ao excluir: {e}")
        return False
