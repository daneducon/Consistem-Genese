import json
import os
import tempfile
import threading
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

def _now_str(fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Horário de exibição (servidor em UTC, usuário em SP por padrão)."""
    try:
        tz = ZoneInfo(os.getenv("TZ_DISPLAY", "America/Sao_Paulo"))
    except Exception:
        tz = None
    return datetime.now(tz).strftime(fmt) if tz else datetime.now().strftime(fmt)

# Vercel serverless: /var/task é read-only — store vai para /tmp (efêmero por
# instância; dados live são reconstruídos do Google a cada listagem).
if os.getenv("VERCEL") or os.getenv("VERCEL_ENV"):
    DATA_FILE = Path(tempfile.gettempdir()) / "genese_notebooks_store.json"
else:
    DATA_FILE = Path(__file__).parent / "data" / "notebooks_store.json"
_lock = threading.Lock()

def _load_store() -> dict:
    if not DATA_FILE.exists():
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_store(store: dict):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    # P3-2: escrita atômica + lock em memória (evita corrupção com --reload)
    with _lock:
        fd, tmp_path = tempfile.mkstemp(dir=str(DATA_FILE.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(store, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, DATA_FILE)
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception:
                pass

def get_all_notebooks_meta() -> dict:
    return _load_store()

def get_notebook_meta(notebook_id: str) -> dict | None:
    store = _load_store()
    return store.get(notebook_id)

def save_notebook_meta(notebook_id: str, title: str, objective: str = "", analysis_md: str = "", sources: list = None, text_context: str = None, owner: str = None) -> dict:
    store = _load_store()
    now_str = _now_str()
    
    current = store.get(notebook_id, {})
    # P2-7: histórico versionado
    history = current.get("analysisHistory", [])
    if analysis_md is not None and current.get("analysisMd") and current.get("analysisMd") != analysis_md:
        history.append({"analysisMd": current.get("analysisMd"), "updatedAt": current.get("updatedAt"), "model": current.get("lastModel", "")})
        # mantém últimas 10 versões
        history = history[-10:]
    entry = {
        "id": notebook_id,
        "title": title or current.get("title", "Sem título"),
        "objective": objective or current.get("objective", ""),
        "analysisMd": analysis_md if analysis_md is not None else current.get("analysisMd", ""),
        "updatedAt": now_str,
        "createdAt": current.get("createdAt", now_str),
        "sources": sources if sources is not None else current.get("sources", []),
        "analysisHistory": history,
        "lastModel": current.get("lastModel", ""),
        "textContext": text_context if text_context is not None else current.get("textContext", ""),
        "owner": owner if owner is not None else current.get("owner", ""),
    }
    if analysis_md is not None:
        from os import getenv
        entry["lastModel"] = getenv("OPENROUTER_MODEL", "")
    store[notebook_id] = entry
    _save_store(store)
    return entry

def update_notebook_meta(notebook_id: str, title: str = None, objective: str = None, analysis_md: str = None, sources: list = None, text_context: str = None, owner: str = None) -> dict | None:
    store = _load_store()
    if notebook_id not in store:
        return save_notebook_meta(notebook_id, title or "Sem título", objective or "", analysis_md or "", sources or [], text_context, owner)
    
    now_str = _now_str()
    if title is not None:
        store[notebook_id]["title"] = title
    if objective is not None:
        store[notebook_id]["objective"] = objective
    if analysis_md is not None:
        # P2-7: arquiva versão anterior
        if store[notebook_id].get("analysisMd") and store[notebook_id].get("analysisMd") != analysis_md:
            hist = store[notebook_id].get("analysisHistory", [])
            hist.append({"analysisMd": store[notebook_id].get("analysisMd"), "updatedAt": store[notebook_id].get("updatedAt"), "model": store[notebook_id].get("lastModel", "")})
            store[notebook_id]["analysisHistory"] = hist[-10:]
        store[notebook_id]["analysisMd"] = analysis_md
        from os import getenv
        store[notebook_id]["lastModel"] = getenv("OPENROUTER_MODEL", "")
    if sources is not None:
        store[notebook_id]["sources"] = sources
    if text_context is not None:
        store[notebook_id]["textContext"] = text_context
    if owner is not None:
        store[notebook_id]["owner"] = owner
    store[notebook_id]["updatedAt"] = now_str
    
    _save_store(store)
    return store[notebook_id]

def delete_notebook_meta(notebook_id: str) -> bool:
    store = _load_store()
    if notebook_id in store:
        del store[notebook_id]
        _save_store(store)
        return True
    return False
