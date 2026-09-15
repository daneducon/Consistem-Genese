import React, { useState, useEffect, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeSanitize from 'rehype-sanitize';
import { GridSkeleton, SourcesSkeleton, MarkdownSkeleton } from './components/Skeleton';
import Tooltip from './components/Tooltip';
import InlineSpinner from './components/InlineSpinner';

const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
const API_KEY = import.meta.env.VITE_API_KEY || '';
const apiHeaders = (extra = {}) => {
  const h = { ...extra };
  if (API_KEY) h['X-API-Key'] = API_KEY;
  return h;
};
const apiFetch = (url, opts = {}) => {
  opts.headers = apiHeaders(opts.headers || {});
  return fetch(url, opts);
};

export default function App() {
  const [notebooks, setNotebooks] = useState([]);
  const [selectedNotebook, setSelectedNotebook] = useState(null);
  const [loadingList, setLoadingList] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionMessage, setActionMessage] = useState('');
  const [feedbackToast, setFeedbackToast] = useState(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [jobProgress, setJobProgress] = useState(0);
  const [loadingPhrase, setLoadingPhrase] = useState(0);
  const loadingPhrases = [
    'Organizando seus materiais...',
    'Consultando o NotebookLM...',
    'Lendo fontes e extraindo contexto...',
    'Acionando Gemma via OpenRouter...',
    'Estruturando pré-diagnóstico...',
    'Selecionando ferramentas de T&D...',
    'Montando roteiro de entrevista...',
    'Quase pronto, refinando a escrita...',
  ];
  const [syncing, setSyncing] = useState(false);
  const [lastSync, setLastSync] = useState(null);
  const [syncCountdown, setSyncCountdown] = useState(0);

  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isAddSourceModalOpen, setIsAddSourceModalOpen] = useState(false);
  const [openMenuId, setOpenMenuId] = useState(null);
  const [editingNotebook, setEditingNotebook] = useState(null);

  const [searchQuery, setSearchQuery] = useState(() => localStorage.getItem('genese_search') || '');
  const [sortBy, setSortBy] = useState(() => localStorage.getItem('genese_sort') || 'updatedAt');
  const [searchInput, setSearchInput] = useState(() => localStorage.getItem('genese_search') || '');
  const [confirmDeleteId, setConfirmDeleteId] = useState(null);
  const [isOffline, setIsOffline] = useState(() => typeof navigator !== 'undefined' ? !navigator.onLine : false);

  const [dragActiveCreate, setDragActiveCreate] = useState(false);
  const [dragActiveAppend, setDragActiveAppend] = useState(false);

  const [formTitle, setFormTitle] = useState('');
  const [formObjective, setFormObjective] = useState('');
  const [files, setFiles] = useState([]);
  const [siteUrl, setSiteUrl] = useState('');
  const [youtubeUrl, setYoutubeUrl] = useState('');

  const [loadingDetail, setLoadingDetail] = useState(false);
  const [sourcesPage, setSourcesPage] = useState(1);
  const SOURCES_PER_PAGE = 12;
  const [showHistory, setShowHistory] = useState(false);
  const [savingEdit, setSavingEdit] = useState(false);

  const showToast = (message, type = 'success', actionLabel = null, onAction = null) => {
    setFeedbackToast({ message, type, actionLabel, onAction });
    setTimeout(() => setFeedbackToast(null), 4000);
  };

  const fetchNotebooks = async () => {
    setLoadingList(true);
    try {
      const res = await apiFetch(`${API_BASE}/api/v1/notebooks`);
      if (res.ok) {
        const data = await res.json();
        setNotebooks(data);
      } else {
        showToast('Erro ao carregar cadernos do servidor.', 'error');
      }
    } catch (err) {
      console.error(err);
      showToast('Falha na conexão com a API local.', 'error');
    } finally {
      setLoadingList(false);
    }
  };

  const fetchNotebookDetail = useCallback(async (notebookId) => {
    setLoadingDetail(true);
    try {
      const res = await apiFetch(`${API_BASE}/api/v1/notebooks/${notebookId}`);
      if (res.ok) {
        const detail = await res.json();
        setSelectedNotebook((prev) => (!prev || prev.id === notebookId ? detail : prev));
        setNotebooks((prev) => prev.map((nb) => (nb.id === notebookId ? { ...nb, ...detail } : nb)));
        setSourcesPage(1);
        return detail;
      } else {
        showToast('Erro ao carregar detalhe do caderno.', 'error');
      }
    } catch (err) {
      console.error('[poll] fetch detail error', err);
      showToast('Falha ao conectar com o detalhe. Tente novamente.', 'error');
    } finally {
      setLoadingDetail(false);
    }
    return null;
  }, []);

  useEffect(() => {
    fetchNotebooks();
  }, []);

  const fetchSyncStatus = async () => {
    try {
      const r = await apiFetch(`${API_BASE}/api/v1/sync/status`);
      if (r.ok) { const j = await r.json(); setLastSync(j.last_sync); }
    } catch { }
  };
  useEffect(() => { fetchSyncStatus(); const id = setInterval(fetchSyncStatus, 300000); return () => clearInterval(id); }, []);

  useEffect(() => {
    if (!syncing) { setSyncCountdown(0); return; }
    setSyncCountdown(6);
    const id = setInterval(() => setSyncCountdown((c) => (c > 0 ? c - 1 : 0)), 1000);
    return () => clearInterval(id);
  }, [syncing]);

  const handleSync = async () => {
    if (syncing) return;
    setSyncing(true);
    try {
      const r = await apiFetch(`${API_BASE}/api/v1/notebooks/sync`, { method: 'POST' });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail || 'Falha ao sincronizar.');
      if (j.cached) {
        setLastSync(j.last_sync);
        await fetchNotebooks();
        showToast(j.warning || 'Sessão expirada — exibindo cache. Rode notebooklm login.', 'error', 'Entendi', () => { });
        return;
      }
      setLastSync(j.last_sync);
      await fetchNotebooks();
      showToast(`Sincronizado — ${j.synced} cadernos`, 'success');
    } catch (e) {
      const msg = e.message.includes('Auth') || e.message.includes('login') ? 'Sessão do Google expirada. No terminal: notebooklm login' : e.message;
      showToast(msg, 'error', 'Tentar novamente', handleSync);
    } finally { setSyncing(false); }
  };

  const handleSelectNotebook = (nb) => {
    setSelectedNotebook(nb);
    fetchNotebookDetail(nb.id);
  };

  const hasIndexingSources = selectedNotebook?.sources?.some((s) => s.status === 'INDEXING');
  useEffect(() => {
    if (!selectedNotebook?.id || !hasIndexingSources) return;
    const interval = setInterval(() => {
      fetchNotebookDetail(selectedNotebook.id);
    }, 4000);
    return () => clearInterval(interval);
  }, [selectedNotebook?.id, hasIndexingSources, fetchNotebookDetail]);

  useEffect(() => {
    const handleOutsideClick = () => setOpenMenuId(null);
    window.addEventListener('click', handleOutsideClick);
    return () => window.removeEventListener('click', handleOutsideClick);
  }, []);

  useEffect(() => {
    if (!actionLoading) { setLoadingPhrase(0); return; }
    const id = setInterval(() => setLoadingPhrase((p) => (p + 1) % loadingPhrases.length), 2200);
    return () => clearInterval(id);
  }, [actionLoading, loadingPhrases.length]);

  // debounce busca (300ms) + persistência + offline
  useEffect(() => {
    const t = setTimeout(() => setSearchQuery(searchInput), 300);
    return () => clearTimeout(t);
  }, [searchInput]);
  useEffect(() => { localStorage.setItem('genese_search', searchQuery); }, [searchQuery]);
  useEffect(() => { localStorage.setItem('genese_sort', sortBy); }, [sortBy]);
  useEffect(() => {
    const onOnline = () => setIsOffline(false);
    const onOffline = () => setIsOffline(true);
    window.addEventListener('online', onOnline);
    window.addEventListener('offline', onOffline);
    return () => { window.removeEventListener('online', onOnline); window.removeEventListener('offline', onOffline); };
  }, []);

  // atalho / para focar busca e Esc para limpar (como na imagem Nexus)
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === '/' && !selectedNotebook && document.activeElement?.tagName !== 'INPUT' && document.activeElement?.tagName !== 'TEXTAREA') {
        e.preventDefault();
        document.getElementById('grid-search')?.focus();
      }
      if (e.key === 'Escape' && searchQuery) { setSearchQuery(''); setSearchInput(''); }
      if (e.key === 'Escape' && confirmDeleteId) setConfirmDeleteId(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [searchQuery, selectedNotebook, confirmDeleteId]);

  const resetForm = () => {
    setFormTitle('');
    setFormObjective('');
    setFiles([]);
    setSiteUrl('');
    setYoutubeUrl('');
    setDragActiveCreate(false);
    setDragActiveAppend(false);
  };

  const handleDragOver = (e, setActive) => {
    e.preventDefault();
    e.stopPropagation();
    setActive(true);
  };
  const handleDragLeave = (e, setActive) => {
    e.preventDefault();
    e.stopPropagation();
    setActive(false);
  };
  const handleDropCreate = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActiveCreate(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const dropped = Array.from(e.dataTransfer.files).filter((f) =>
        /\.(pdf|md|txt|png|jpg|jpeg|webp)$/i.test(f.name) || f.type.startsWith('image/') || f.type === 'application/pdf' || f.type === 'text/plain'
      );
      if (dropped.length > 0) setFiles((prev) => [...prev, ...dropped]);
      else showToast('Formato não suportado. Use PDF, MD, TXT, PNG, JPG.', 'error');
    }
  };
  const handleDropAppend = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActiveAppend(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const dropped = Array.from(e.dataTransfer.files).filter((f) =>
        /\.(pdf|md|txt|png|jpg|jpeg|webp)$/i.test(f.name) || f.type.startsWith('image/') || f.type === 'application/pdf' || f.type === 'text/plain'
      );
      if (dropped.length > 0) setFiles((prev) => [...prev, ...dropped]);
      else showToast('Formato não suportado. Use PDF, MD, TXT, PNG, JPG.', 'error');
    }
  };
  const removeFileAt = (idx) => setFiles((prev) => prev.filter((_, i) => i !== idx));
  const parseLinks = (text) => text.split(/[,;\n]+/).map((s) => s.trim()).filter(Boolean);
  const removeSiteUrlAt = (idx) => {
    const links = parseLinks(siteUrl);
    links.splice(idx, 1);
    setSiteUrl(links.join(', '));
  };
  const removeYoutubeUrlAt = (idx) => {
    const links = parseLinks(youtubeUrl);
    links.splice(idx, 1);
    setYoutubeUrl(links.join(', '));
  };

  const xhrPostWithProgress = (url, formData, onProgress) => new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', url);
    if (API_KEY) xhr.setRequestHeader('X-API-Key', API_KEY);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100)); };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) { try { resolve(JSON.parse(xhr.responseText)); } catch { resolve(xhr.responseText); } }
      else { try { const j = JSON.parse(xhr.responseText); reject(new Error(j.detail || xhr.statusText)); } catch { reject(new Error(xhr.statusText)); } }
    };
    xhr.onerror = () => reject(new Error('Falha de rede'));
    xhr.send(formData);
  });
  const pollJob = async (jobId, onUpdate) => {
    for (let i = 0; i < 120; i++) {
      const r = await apiFetch(`${API_BASE}/api/v1/jobs/${jobId}`);
      if (!r.ok) throw new Error('Job não encontrado');
      const job = await r.json();
      if (onUpdate) onUpdate(job);
      if (job.status === 'done') return job;
      if (job.status === 'error') throw new Error(job.error || job.message);
      await new Promise((res) => setTimeout(res, 1000));
    }
    throw new Error('Timeout do job');
  };

  const handleCreateNotebook = async (e) => {
    e.preventDefault();
    if (!formTitle.trim()) return;
    setActionLoading(true);
    setUploadProgress(0);
    setJobProgress(0);
    setActionMessage('Enviando arquivos...');
    const formData = new FormData();
    formData.append('project_title', formTitle.trim());
    formData.append('project_objective', formObjective.trim());
    Array.from(files).forEach((f) => formData.append('files', f));
    if (siteUrl.trim()) formData.append('site_url', siteUrl.trim());
    if (youtubeUrl.trim()) formData.append('youtube_url', youtubeUrl.trim());
    try {
      let jobRes;
      try {
        jobRes = await xhrPostWithProgress(`${API_BASE}/api/v1/notebooks/create-and-analyze-async`, formData, (p) => setUploadProgress(p));
      } catch (xhrErr) {
        const res = await apiFetch(`${API_BASE}/api/v1/notebooks/create-and-analyze`, { method: 'POST', body: formData, headers: apiHeaders() });
        if (!res.ok) { const j = await res.json().catch(() => ({})); throw new Error(j.detail || 'Erro ao criar'); }
        const createdNb = await res.json();
        setNotebooks((prev) => [createdNb, ...prev]);
        setSelectedNotebook(createdNb);
        setIsCreateModalOpen(false);
        resetForm();
        showToast(`Caderno "${createdNb.title}" criado!`);
        return;
      }
      const jobId = jobRes.job_id;
      setActionMessage('Na fila — aguardando worker...');
      const job = await pollJob(jobId, (j) => { setActionMessage(j.message || 'Processando...'); setJobProgress(j.progress || 0); });
      const createdNb = job.result;
      setNotebooks((prev) => [createdNb, ...prev]);
      setSelectedNotebook(createdNb);
      setIsCreateModalOpen(false);
      resetForm();
      showToast(`Caderno "${createdNb.title}" criado e analisado!`);
    } catch (err) {
      console.error(err);
      showToast(err.message, 'error', 'Tentar novamente', () => handleCreateNotebook(e));
    } finally {
      setActionLoading(false);
      setActionMessage('');
      setUploadProgress(0);
      setJobProgress(0);
    }
  };

  const handleSaveEdit = async (e) => {
    e.preventDefault();
    const target = editingNotebook || selectedNotebook;
    if (!target) return;
    setSavingEdit(true);
    try {
      const res = await apiFetch(`${API_BASE}/api/v1/notebooks/${target.id}`, {
        method: 'PUT',
        headers: apiHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ title: formTitle.trim(), objective: formObjective.trim() }),
      });
      if (!res.ok) throw new Error('Falha ao atualizar dados do caderno.');
      const updated = await res.json();
      setNotebooks((prev) => prev.map((nb) => (nb.id === updated.id ? { ...nb, ...updated } : nb)));
      setSelectedNotebook((prev) => (prev && prev.id === updated.id ? { ...prev, ...updated } : prev));
      setIsEditModalOpen(false);
      setEditingNotebook(null);
      resetForm();
      showToast('Caderno atualizado com sucesso!');
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      setSavingEdit(false);
    }
  };

  const confirmDelete = (id) => setConfirmDeleteId(id);
  const handleDeleteNotebook = async (id, e) => {
    if (e) e.stopPropagation();
    const backup = notebooks.find((nb) => nb.id === id);
    const prevSelected = selectedNotebook;
    try {
      const res = await apiFetch(`${API_BASE}/api/v1/notebooks/${id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('Falha ao excluir o caderno.');
      setNotebooks((prev) => prev.filter((nb) => nb.id !== id));
      if (selectedNotebook?.id === id) setSelectedNotebook(null);
      setOpenMenuId(null);
      showToast('Caderno removido.', 'success', 'Desfazer', () => {
        if (backup) {
          setNotebooks((prev) => [backup, ...prev]);
          if (prevSelected?.id === id) setSelectedNotebook(prevSelected);
          showToast('Exclusão desfeita localmente. No Google já foi excluído — recrie se necessário.', 'error');
        }
      });
    } catch (err) {
      showToast(err.message, 'error', 'Tentar novamente', () => handleDeleteNotebook(id, e));
    }
  };

  const handleAppendSource = async (e) => {
    e.preventDefault();
    if (!selectedNotebook) return;
    if (files.length === 0 && !siteUrl.trim() && !youtubeUrl.trim()) {
      showToast('Selecione ao menos um arquivo, link ou vídeo.', 'error');
      return;
    }
    setActionLoading(true);
    setUploadProgress(0);
    setActionMessage('Enviando novas fontes...');
    const formData = new FormData();
    Array.from(files).forEach((f) => formData.append('files', f));
    if (siteUrl.trim()) formData.append('site_url', siteUrl.trim());
    if (youtubeUrl.trim()) formData.append('youtube_url', youtubeUrl.trim());
    try {
      const result = await xhrPostWithProgress(`${API_BASE}/api/v1/notebooks/${selectedNotebook.id}/append`, formData, (p) => setUploadProgress(p));
      const updatedNb = { ...selectedNotebook, sources: result.sources, sourcesCount: result.sourcesCount };
      setSelectedNotebook(updatedNb);
      setNotebooks((prev) => prev.map((nb) => (nb.id === updatedNb.id ? updatedNb : nb)));
      setIsAddSourceModalOpen(false);
      resetForm();
      showToast('Novas fontes vinculadas com sucesso!');
      setTimeout(() => fetchNotebookDetail(selectedNotebook.id), 1500);
    } catch (err) {
      try {
        const res = await apiFetch(`${API_BASE}/api/v1/notebooks/${selectedNotebook.id}/append`, { method: 'POST', body: formData, headers: apiHeaders() });
        if (!res.ok) throw new Error('Falha ao anexar fontes ao caderno.');
        const result = await res.json();
        const updatedNb = { ...selectedNotebook, sources: result.sources, sourcesCount: result.sourcesCount };
        setSelectedNotebook(updatedNb);
        setNotebooks((prev) => prev.map((nb) => (nb.id === updatedNb.id ? updatedNb : nb)));
        setIsAddSourceModalOpen(false);
        resetForm();
        showToast('Novas fontes vinculadas!');
      } catch (e2) {
        showToast(err.message || e2.message, 'error');
      }
    } finally {
      setActionLoading(false);
      setActionMessage('');
      setUploadProgress(0);
    }
  };

  const handleReanalyze = async () => {
    if (!selectedNotebook) return;
    setActionLoading(true);
    setJobProgress(0);
    setActionMessage('Solicitando re-análise GEM...');
    try {
      const r = await apiFetch(`${API_BASE}/api/v1/notebooks/${selectedNotebook.id}/reanalyze-async`, { method: 'POST' });
      if (!r.ok) {
        const res = await apiFetch(`${API_BASE}/api/v1/notebooks/${selectedNotebook.id}/reanalyze`, { method: 'POST' });
        if (!res.ok) throw new Error('Falha ao reanalisar o caderno.');
        const result = await res.json();
        const updatedNb = { ...selectedNotebook, analysisMd: result.analysisMd, updatedAt: result.updatedAt };
        setSelectedNotebook(updatedNb);
        setNotebooks((prev) => prev.map((nb) => (nb.id === updatedNb.id ? updatedNb : nb)));
        showToast('Pré-análise atualizada com sucesso!');
        return;
      }
      const { job_id } = await r.json();
      const job = await pollJob(job_id, (j) => { setActionMessage(j.message || 'Processando GEM...'); setJobProgress(j.progress || 0); });
      const result = job.result;
      const updatedNb = { ...selectedNotebook, analysisMd: result.analysisMd, updatedAt: result.updatedAt };
      setSelectedNotebook(updatedNb);
      setNotebooks((prev) => prev.map((nb) => (nb.id === updatedNb.notebook_id ? updatedNb : nb)));
      fetchNotebookDetail(selectedNotebook.id);
      showToast('Pré-análise atualizada com sucesso!');
    } catch (err) {
      showToast(err.message, 'error', 'Tentar novamente', handleReanalyze);
    } finally {
      setActionLoading(false);
      setActionMessage('');
      setJobProgress(0);
    }
  };

  const handleCopyMd = async () => {
    if (!selectedNotebook?.analysisMd) return;
    try {
      await navigator.clipboard.writeText(selectedNotebook.analysisMd);
      showToast('Análise copiada para a área de transferência!');
    } catch (err) {
      console.error(err);
      const ta = document.createElement('textarea');
      ta.value = selectedNotebook.analysisMd;
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand('copy');
        showToast('Análise copiada para a área de transferência!');
      } catch (e2) {
        showToast('Falha ao copiar. Selecione o texto manualmente.', 'error');
      }
      document.body.removeChild(ta);
    }
  };

  const handleDownloadMd = () => {
    if (!selectedNotebook?.analysisMd) return;
    const blob = new Blob([selectedNotebook.analysisMd], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const element = document.createElement('a');
    element.href = url;
    const safeName = selectedNotebook.title.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/gi, '_').replace(/^_+|_+$/g, '');
    element.download = `${safeName || 'caderno'}_diagnostico.md`;
    document.body.appendChild(element);
    element.click();
    document.body.removeChild(element);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    showToast('Download do arquivo .md concluído!');
  };

  const openEditModal = (nb, e) => {
    e.stopPropagation();
    setEditingNotebook(nb);
    setFormTitle(nb.title);
    setFormObjective(nb.objective || '');
    setIsEditModalOpen(true);
    setOpenMenuId(null);
  };

  const formatDate = (d) => {
    if (!d) return 'Recente';
    // Espera YYYY-MM-DD HH:MM ou ISO; retorna DD/MM/AAAA-HH:MM
    try {
      const s = String(d).trim();
      // já está em DD/MM ?
      if (/^\d{2}\/\d{2}\/\d{4}/.test(s)) return s.replace(' ', '-');
      const m = s.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
      if (m) return `${m[3]}/${m[2]}/${m[1]}-${m[4]}:${m[5]}`;
      const dt = new Date(s);
      if (!isNaN(dt.getTime())) {
        const dd = String(dt.getDate()).padStart(2, '0');
        const mm = String(dt.getMonth() + 1).padStart(2, '0');
        const yyyy = dt.getFullYear();
        const hh = String(dt.getHours()).padStart(2, '0');
        const mi = String(dt.getMinutes()).padStart(2, '0');
        return `${dd}/${mm}/${yyyy}-${hh}:${mi}`;
      }
    } catch { }
    return d;
  };

  const filteredNotebooks = React.useMemo(() => {
    let list = [...notebooks];
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      list = list.filter((nb) => nb.title.toLowerCase().includes(q) || (nb.objective || '').toLowerCase().includes(q));
    }
    list.sort((a, b) => {
      if (sortBy === 'title') return a.title.localeCompare(b.title);
      if (sortBy === 'sourcesCount') return (b.sourcesCount || 0) - (a.sourcesCount || 0);
      return (b.updatedAt || '').localeCompare(a.updatedAt || '');
    });
    return list;
  }, [notebooks, searchQuery, sortBy]);

  const paginatedSources = React.useMemo(() => {
    const srcs = selectedNotebook?.sources || [];
    return srcs.slice(0, sourcesPage * SOURCES_PER_PAGE);
  }, [selectedNotebook?.sources, sourcesPage]);
  const hasMoreSources = (selectedNotebook?.sources?.length || 0) > paginatedSources.length;

  const suggestionChips = ['Cadastro de Engenharia', 'Guia do Conteudista', 'Onboarding Comercial Gênese'];

  // Normaliza markdown do GEM para dar respiro: negritos "Contexto Geral:" viram headings
  const displayMd = React.useMemo(() => {
    let t = selectedNotebook?.analysisMd || '';
    if (!t) return '';
    t = t.replace(/\r\n/g, '\n');
    // garante linha em branco antes de headings numerados
    t = t.replace(/(\n)(\d+\.\s+[A-ZÁÂÃÉÊÍÓÔÕÚÇ])/g, '\n\n$2');
    // **Título:** -> ### Título
    t = t.replace(/\n\*\*(.+?:)\*\*\s*\n/g, '\n\n### $1\n\n');
    t = t.replace(/\n\*\*(.+?:)\*\*/g, '\n\n### $1\n');
    // linhas curtas que terminam com : e são seguidas de texto longo -> heading
    t = t.replace(/\n([A-ZÁÂÃÉÊÍÓÔÕÚÇ][^:\n]{3,50}:)\s*\n/g, '\n\n### $1\n\n');
    return t;
  }, [selectedNotebook?.analysisMd]);

  return (
    <div className="min-h-screen bg-[#f8f9fa] text-[#191c1d] font-['DM_Sans'] selection:bg-[#2e2e30] selection:text-white">
      <div className="max-w-[1280px] mx-auto px-4 md:px-10">
        {feedbackToast && (
          <div className="fixed top-6 right-6 z-50">
            <div className={`px-4 py-3 rounded-lg shadow-[0_4px_20px_-2px_rgba(46,46,48,0.08)] border text-xs font-medium flex items-center gap-3 ${feedbackToast.type === 'error' ? 'bg-[#ffdad6] border-[#ffdad6] text-[#93000a]' : 'bg-[#eaf7f0] border-[#eaf7f0] text-[#2e9e66]'}`}>
              <span>{feedbackToast.message}</span>
              {feedbackToast.actionLabel && feedbackToast.onAction && (
                <button onClick={() => { feedbackToast.onAction(); setFeedbackToast(null); }} className="ml-1 px-3 py-1 bg-[#191c1d] text-white rounded-full text-[11px] font-medium"> {feedbackToast.actionLabel} </button>
              )}
              <button onClick={() => setFeedbackToast(null)} className="text-[#46464a]">Fechar</button>
            </div>
          </div>
        )}

        {actionLoading && (
          <div className="fixed inset-0 bg-[#f8f9fa]/85 backdrop-blur-sm z-50 flex flex-col items-center justify-center p-6 text-center">
            <div className="w-10 h-10 border-2 border-[#2e2e30] border-t-transparent rounded-full animate-spin"></div>
            <p className="mt-4 text-sm font-medium text-[#191c1d]">{actionMessage || 'Processando...'}</p>
            <p className="mt-1 text-xs text-[#46464a] animate-pulse min-h-[16px]">{loadingPhrases[loadingPhrase]}</p>
            {(uploadProgress > 0 && uploadProgress < 100) && (
              <div className="mt-3 w-64">
                <div className="flex justify-between text-[11px] text-[#46464a] mb-1"><span>Upload</span><span>{uploadProgress}%</span></div>
                <div className="h-1 bg-[#e1e3e4] rounded-full overflow-hidden"><div className="h-full bg-[#2e9e66] transition-all" style={{ width: `${uploadProgress}%` }}></div></div>
              </div>
            )}
            {(jobProgress > 0 && jobProgress < 100) && (
              <div className="mt-2 w-64">
                <div className="flex justify-between text-[11px] text-[#46464a] mb-1"><span>Progresso</span><span>{jobProgress}%</span></div>
                <div className="h-1 bg-[#e1e3e4] rounded-full overflow-hidden"><div className="h-full bg-[#df5241] transition-all" style={{ width: `${jobProgress}%` }}></div></div>
              </div>
            )}
            <p className="mt-3 text-[11px] text-[#a5a5ab]">Isso pode levar até 60s · não feche a janela</p>
          </div>
        )}

        <header className="sticky top-4 z-20 mt-4 mb-6 bg-white border border-[#e8e9eb] rounded-2xl px-5 md:px-6 h-[64px] flex justify-between items-center shadow-[0_4px_24px_-4px_rgba(46,46,48,0.08)]">
          <div className="flex items-center gap-4">
            <img src="/logo_genese.png" alt="Consistem Gênese" className="h-8 md:h-9 w-auto object-contain" />
            <span className="hidden md:block h-5 w-px bg-[#e8e9eb]"></span>
            <div className="hidden md:block leading-none">
              <p className="text-xs font-medium text-[#191c1d] leading-none">Consistem Gênese</p>
              <p className="text-[11px] text-[#a5a5ab] leading-none mt-0.5">Diagnóstico de T&D · NotebookLM</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {selectedNotebook && (
              <button onClick={() => setSelectedNotebook(null)} className="px-4 h-9 bg-[#f8f9fa] hover:bg-white border border-[#e8e9eb] rounded-full text-xs font-medium text-[#191c1d] transition-colors">Voltar</button>
            )}
            <button onClick={() => { resetForm(); setIsCreateModalOpen(true); }} className="h-9 px-5 bg-[#df5241] hover:bg-[#c84434] text-white rounded-full text-xs font-medium shadow-[0_2px_10px_rgba(223,82,65,0.2)] hover:shadow-[0_4px_16px_rgba(223,82,65,0.28)] transition-all">Criar novo caderno</button>
          </div>
        </header>

        {!selectedNotebook && (
          <div className="pb-10">
            <section className="pt-2 pb-6 max-w-[720px]">
              <p className="text-[11px] font-semibold tracking-[0.08em] uppercase text-[#df5241]">Diagnóstico de T&D</p>
              <h1 className="mt-2 text-[32px] md:text-[40px] font-semibold tracking-[-0.02em] leading-[0.95] text-[#191c1d]">Analise cenários.</h1>
              <h1 className="text-[32px] md:text-[40px] font-semibold tracking-[-0.02em] leading-[0.95] text-[#191c1d]">Estruture treinamentos.</h1>
              <p className="mt-4 text-sm leading-6 text-[#46464a]">Reúna seus materiais em um só lugar e receba diagnósticos de T&D com roteiros de entrevista em segundos.</p>

              <div className="mt-6">
                <div className="relative">
                  <input
                    id="grid-search"
                    type="text"
                    value={searchInput}
                    onChange={(e) => setSearchInput(e.target.value)}
                    placeholder="Buscar cadernos criados..."
                    aria-label="Buscar cadernos"
                    className="w-full h-[48px] pl-4 pr-10 bg-white border border-[#c7c6ca] rounded-xl text-sm text-[#191c1d] placeholder:text-[#a5a5ab] focus:outline-none focus:border-[#191c1d] focus:ring-2 focus:ring-[#191c1d]/10 shadow-[0_4px_20px_-2px_rgba(46,46,48,0.04)]"
                  />
                  {searchInput && (
                    <button onClick={() => { setSearchInput(''); setSearchQuery(''); }} aria-label="Limpar busca" className="absolute right-3 top-1/2 -translate-y-1/2 w-6 h-6 flex items-center justify-center rounded-full hover:bg-[#f8f9fa] text-[#46464a]">×</button>
                  )}
                </div>
                <p className="mt-2 text-[11px] text-[#46464a] flex items-center gap-1.5"><span className="inline-flex items-center justify-center min-w-[16px] h-4 px-1 bg-white border border-[#e8e9eb] rounded text-[10px] font-medium">/</span> buscar <span className="inline-flex items-center justify-center min-w-[22px] h-4 px-1 bg-white border border-[#e8e9eb] rounded text-[10px] font-medium">Esc</span> limpar</p>
                <div className="mt-4 flex flex-wrap items-center gap-2">
                  {suggestionChips.map((s) => (
                    <button key={s} onClick={() => { setSearchInput(s); setSearchQuery(s); }} className="px-3 py-1.5 bg-[#26272b] hover:bg-[#2e2e30] border border-[#26272b] rounded-full text-xs text-white transition-colors focus:outline-none focus:ring-2 focus:ring-[#191c1d]/20">{s}</button>
                  ))}
                </div>
              </div>
            </section>
            <div className="mt-6 mb-6 flex items-center gap-3">
              <select value={sortBy} onChange={(e) => setSortBy(e.target.value)} className="px-3 py-2 bg-white border border-[#e8e9eb] rounded-full text-xs text-[#191c1d] focus:outline-none">
                <option value="updatedAt">Mais recentes</option>
                <option value="title">A-Z</option>
                <option value="sourcesCount">Mais fontes</option>
              </select>
              <span className="text-xs text-[#46464a]" aria-live="polite">{filteredNotebooks.length} cadernos{searchQuery && ` para "${searchQuery}"`}</span>
              {searchQuery && <button onClick={() => { setSearchQuery(''); setSearchInput(''); }} className="text-xs text-[#46464a] underline focus:outline-none focus:ring-2 focus:ring-[#191c1d]/20 rounded">Limpar busca</button>}
              <Tooltip content={syncing ? `Sincronizando... ${syncCountdown}s` : lastSync ? `Última sincronização: ${lastSync}` : 'Sincronizar com NotebookLM agora'} side="top">
                <button onClick={handleSync} disabled={syncing} className="ml-auto inline-flex items-center gap-1.5 px-3 py-1.5 bg-[#eaf7f0] hover:bg-[#d8f0e3] border border-[#eaf7f0] rounded-full text-xs font-medium text-[#2e9e66] disabled:opacity-50 transition-colors">
                  {syncing ? <InlineSpinner size={10} light={false} className="border-[#2e9e66] border-t-transparent" /> : <span className="w-1.5 h-1.5 rounded-full bg-[#2e9e66]"></span>}{syncing ? `Sincronizando... ${syncCountdown}s` : lastSync ? `Sincronizado · ${lastSync}` : 'Sincronizado'}
                </button>
              </Tooltip>
            </div>
            {loadingList ? (
              <GridSkeleton count={6} />
            ) : notebooks.length === 0 ? (
              <div className="py-16 text-center bg-white border border-dashed border-[#c7c6ca] rounded-xl px-6">
                <div className="w-10 h-10 mx-auto flex items-center justify-center rounded-full bg-[#f8f9fa] border border-[#e8e9eb] text-[#a5a5ab]">＋</div>
                <p className="mt-3 text-sm font-medium text-[#191c1d]">Nenhum caderno cadastrado</p>
                <p className="text-xs text-[#46464a] mt-1 max-w-md mx-auto">Reúna PDFs, links e vídeos e gere seu primeiro diagnóstico de T&D com Gemma em segundos.</p>
                <button onClick={() => { resetForm(); setIsCreateModalOpen(true); }} className="mt-4 px-5 py-2 bg-[#df5241] hover:bg-[#c84434] text-white rounded-full text-xs font-medium focus:outline-none focus:ring-2 focus:ring-[#df5241]/20">Criar novo caderno</button>
              </div>
            ) : filteredNotebooks.length === 0 ? (
              <div className="py-16 text-center bg-white border border-[#e8e9eb] rounded-xl px-6">
                <p className="text-sm text-[#191c1d]">Nenhum resultado para "{searchQuery}"</p>
                <p className="text-xs text-[#46464a] mt-1">{notebooks.length} cadernos no total — tente outro termo ou limpe os filtros.</p>
                <button onClick={() => { setSearchQuery(''); setSearchInput(''); }} className="mt-3 px-4 py-2 bg-white border border-[#e8e9eb] rounded-full text-xs text-[#191c1d] focus:outline-none focus:ring-2 focus:ring-[#191c1d]/20">Limpar busca</button>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {filteredNotebooks.map((nb) => (
                  <div key={nb.id} onClick={() => handleSelectNotebook(nb)} className="bg-white border border-[#e8e9eb] rounded-xl p-6 shadow-[0_4px_20px_-2px_rgba(46,46,48,0.04)] hover:shadow-[0_8px_24px_-4px_rgba(46,46,48,0.08)] transition-all cursor-pointer flex flex-col min-h-[180px] group">
                    <div className="flex justify-between items-start gap-2">
                      <Tooltip content={nb.title} side="top">
                        <h3 className="text-base font-semibold leading-5 text-[#191c1d] line-clamp-2 group-hover:text-[#2e2e30] flex-1">{nb.title}</h3>
                      </Tooltip>
                      <div className="relative" onClick={(e) => e.stopPropagation()}>
                        <Tooltip content="Mais ações" side="top">
                          <button onClick={(e) => { e.stopPropagation(); setOpenMenuId(openMenuId === nb.id ? null : nb.id); }} aria-label="Mais ações" className="w-6 h-6 flex items-center justify-center rounded-full hover:bg-[#f8f9fa] text-[#a5a5ab] text-sm">⋮</button>
                        </Tooltip>
                        {openMenuId === nb.id && (
                          <div className="absolute right-0 mt-1 w-40 bg-white border border-[#e8e9eb] rounded-xl shadow-[0_4px_20px_-2px_rgba(46,46,48,0.08)] z-30 py-1 text-xs">
                            <button onClick={(e) => openEditModal(nb, e)} className="w-full text-left px-3 py-2 hover:bg-[#f8f9fa] text-[#191c1d] focus:bg-[#f8f9fa] focus:outline-none">Editar caderno</button>
                            <button onClick={(e) => { e.stopPropagation(); confirmDelete(nb.id); setOpenMenuId(null); }} className="w-full text-left px-3 py-2 hover:bg-[#fff5f4] text-[#ba1a1a] focus:bg-[#fff5f4] focus:outline-none">Excluir</button>
                          </div>
                        )}
                      </div>
                    </div>
                    <Tooltip content={nb.objective || 'Sem objetivo definido.'} side="top">
                      <p className="mt-2 text-sm leading-6 text-[#46464a] line-clamp-2">{nb.objective || 'Sem objetivo definido.'}</p>
                    </Tooltip>
                    <div className="mt-auto pt-4 flex justify-between items-center text-[11px] text-[#46464a]">
                      <Tooltip content={`${nb.sourcesCount || (nb.sources ? nb.sources.length : 0)} fonte(s) vinculada(s)`}>
                        <span>{nb.sourcesCount || (nb.sources ? nb.sources.length : 0)} fontes</span>
                      </Tooltip>
                      <Tooltip content={`Atualizado em ${formatDate(nb.updatedAt)}`}>
                        <span>{formatDate(nb.updatedAt)}</span>
                      </Tooltip>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {selectedNotebook && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 pb-10 mt-2">
            <div className="lg:col-span-4 bg-white border border-[#e8e9eb] rounded-xl p-6 shadow-[0_4px_20px_-2px_rgba(46,46,48,0.04)] h-fit">
              <div className="flex justify-between items-center">
                <div>
                  <h2 className="text-sm font-semibold text-[#191c1d]">Fontes indexadas</h2>
                  <p className="text-[11px] text-[#46464a]">Materiais vinculados</p>
                </div>
                <span className="text-xs font-medium text-[#191c1d] bg-[#f8f9fa] border border-[#e8e9eb] px-2 py-1 rounded-full">{selectedNotebook.sources?.length || 0}</span>
              </div>

              {loadingDetail && <SourcesSkeleton rows={4} />}

              {hasIndexingSources && !loadingDetail && (
                <div className="mt-4 px-3 py-2 bg-[#fcf5e5] border border-[#fcf5e5] rounded-lg text-[11px] text-[#9c7013]">Indexando {selectedNotebook.sources.filter((s) => s.status === 'INDEXING').length} fonte(s) — atualização automática</div>
              )}

              <div className="mt-4 space-y-2 max-h-[420px] overflow-y-auto pr-1">
                {!loadingDetail && (!selectedNotebook.sources || selectedNotebook.sources.length === 0) ? (
                  <div className="py-8 text-center text-xs text-[#a5a5ab]">Nenhuma fonte vinculada.</div>
                ) : !loadingDetail && (
                  paginatedSources.map((s, idx) => (
                    <div key={s.id || idx} className="px-3 py-2.5 bg-[#f8f9fa] border border-[#e8e9eb] rounded-lg flex justify-between items-center gap-2">
                      <Tooltip content={s.name} side="top">
                        <span className="truncate text-xs text-[#191c1d] max-w-[170px]">{s.name}</span>
                      </Tooltip>
                      <Tooltip content={s.status === 'READY' ? 'Fonte indexada e pronta para análise' : 'Indexando no NotebookLM — atualização automática a cada 4s'} side="top">
                        <span className={`text-[11px] font-medium px-2 py-0.5 rounded-full shrink-0 inline-flex items-center gap-1 ${s.status === 'READY' ? 'bg-[#eaf7f0] text-[#2e9e66]' : 'bg-[#fcf5e5] text-[#9c7013]'}`}>{s.status !== 'READY' && <InlineSpinner size={10} className="border-[#9c7013] border-t-transparent" />}{s.status === 'READY' ? 'Pronto' : 'Indexando...'}</span>
                      </Tooltip>
                    </div>
                  ))
                )}
                {hasMoreSources && !loadingDetail && (
                  <button onClick={() => setSourcesPage((p) => p + 1)} className="w-full py-2 text-xs text-[#191c1d] border border-[#e8e9eb] rounded-lg bg-white hover:bg-[#f8f9fa]">Ver mais {selectedNotebook.sources.length - paginatedSources.length}</button>
                )}
                {sourcesPage > 1 && !hasMoreSources && (
                  <button onClick={() => setSourcesPage(1)} className="w-full py-1 text-[11px] text-[#46464a]">Recolher</button>
                )}
              </div>

              <div className="mt-4 flex gap-2">
                <button onClick={() => { resetForm(); setIsAddSourceModalOpen(true); }} className="flex-1 py-2.5 bg-white border border-[#e8e9eb] rounded-full text-xs font-medium text-[#191c1d] hover:bg-[#f8f9fa]">Adicionar nova fonte</button>
                <Tooltip content={loadingDetail ? 'Atualizando fontes...' : 'Recarregar fontes do NotebookLM'} side="top">
                  <button onClick={() => fetchNotebookDetail(selectedNotebook.id)} disabled={loadingDetail} className="inline-flex items-center gap-1.5 px-3 py-2 bg-white border border-[#e8e9eb] rounded-full text-xs text-[#191c1d] disabled:opacity-40 hover:bg-[#f8f9fa]">
                    {loadingDetail && <InlineSpinner size={12} />}Atualizar
                  </button>
                </Tooltip>
              </div>

              {selectedNotebook.google_notebook_url && (
                <a href={selectedNotebook.google_notebook_url} target="_blank" rel="noreferrer" className="mt-2 block text-center py-2 text-xs text-[#2447b1] underline decoration-[#2447b1]/30 hover:text-[#1a3a8a] hover:decoration-[#2447b1] underline-offset-2">Abrir no NotebookLM</a>
              )}
            </div>

            <div className="lg:col-span-8 bg-white border border-[#e8e9eb] rounded-xl p-6 md:p-8 shadow-[0_4px_20px_-2px_rgba(46,46,48,0.04)]">
              <div className="flex flex-wrap justify-between gap-4">
                <div>
                  <h2 className="text-lg font-semibold tracking-[-0.02em] text-[#191c1d]">{selectedNotebook.title}</h2>
                  <p className="text-sm text-[#46464a] mt-1">{selectedNotebook.objective || 'Sem objetivo definido.'}</p>
                </div>
                <div className="flex items-center gap-2 self-start">
                  <Tooltip content={!selectedNotebook.analysisMd ? 'Nenhuma análise para copiar' : 'Copiar markdown para área de transferência'} side="top">
                    <button onClick={handleCopyMd} disabled={!selectedNotebook.analysisMd} className="px-4 py-2 bg-white border border-[#e8e9eb] rounded-full text-xs font-medium text-[#191c1d] disabled:opacity-40 hover:bg-[#f8f9fa]">Copiar</button>
                  </Tooltip>
                  <Tooltip content={!selectedNotebook.analysisMd ? 'Gere a análise primeiro' : 'Baixar arquivo .md'} side="top">
                    <button onClick={handleDownloadMd} disabled={!selectedNotebook.analysisMd} className="px-5 py-2 bg-[#df5241] hover:bg-[#c84434] text-white rounded-full text-xs font-medium disabled:opacity-40">Baixar .md</button>
                  </Tooltip>
                </div>
              </div>

              <div className="mt-6 max-h-[560px] overflow-y-auto pr-3 -mr-1 text-[#191c1d] scroll-pb-4">
                {loadingDetail ? (
                  <MarkdownSkeleton />
                ) : displayMd ? (
                  <div className="text-[14px] leading-[22px] text-[#46464a]">
                    <ReactMarkdown
                      rehypePlugins={[rehypeSanitize]}
                      components={{
                        h1: ({ children }) => <h1 className="text-[20px] font-semibold tracking-[-0.02em] leading-6 text-[#191c1d] mt-10 mb-4 pb-3 border-b border-[#e8e9eb]">{children}</h1>,
                        h2: ({ children }) => <h2 className="text-[16px] font-semibold tracking-[-0.02em] leading-5 text-[#191c1d] mt-8 mb-4">{children}</h2>,
                        h3: ({ children }) => <h3 className="text-[14px] font-semibold leading-5 text-[#191c1d] mt-6 mb-3">{children}</h3>,
                        p: ({ children }) => <p className="text-[14px] leading-[22px] my-4 text-[#46464a]">{children}</p>,
                        ul: ({ children }) => <ul className="my-5 list-disc pl-5 space-y-2 marker:text-[#a5a5ab]">{children}</ul>,
                        ol: ({ children }) => <ol className="my-5 list-decimal pl-5 space-y-2 marker:text-[#a5a5ab]">{children}</ol>,
                        li: ({ children }) => <li className="text-[14px] leading-6 my-2 text-[#46464a]">{children}</li>,
                        strong: ({ children }) => <strong className="font-semibold text-[#191c1d]">{children}</strong>,
                        em: ({ children }) => <em className="italic text-[#46464a]">{children}</em>,
                        blockquote: ({ children }) => <blockquote className="border-l-2 border-[#e8e9eb] pl-4 my-5 text-[#46464a] italic">{children}</blockquote>,
                        code: ({ children }) => <code className="text-[13px] bg-[#f8f9fa] border border-[#e8e9eb] px-1.5 py-0.5 rounded font-normal text-[#191c1d]">{children}</code>,
                        pre: ({ children }) => <pre className="bg-[#f8f9fa] border border-[#e8e9eb] rounded-xl p-4 my-5 overflow-x-auto">{children}</pre>,
                        hr: () => <hr className="my-8 border-[#e8e9eb]" />,
                        a: ({ children, href }) => <a href={href} className="text-[#2447b1] underline decoration-[#2447b1]/30 hover:decoration-[#2447b1] hover:text-[#1a3a8a] underline-offset-2" target="_blank" rel="noreferrer noopener">{children}</a>,
                      }}
                    >{displayMd}</ReactMarkdown>
                  </div>
                ) : (
                  <div className="py-12 text-center">
                    <p className="text-sm text-[#191c1d]">Nenhum diagnóstico gerado ainda.</p>
                    <p className="text-xs text-[#46464a] mt-1">Atualize a pré-análise para gerar com o GEM.</p>
                  </div>
                )}
              </div>

              {selectedNotebook.analysisHistory && selectedNotebook.analysisHistory.length > 0 && (
                <div className="mt-6 border border-[#e8e9eb] rounded-xl overflow-hidden">
                  <button onClick={() => setShowHistory(!showHistory)} className="w-full flex justify-between items-center px-4 py-3 bg-[#f8f9fa] text-xs text-[#191c1d]">
                    <span>Histórico — {selectedNotebook.analysisHistory.length} versões</span>
                    <span className="text-[#46464a]">{showHistory ? 'Recolher' : 'Ver'}</span>
                  </button>
                  {showHistory && (
                    <div className="max-h-64 overflow-y-auto p-3 space-y-2 bg-white">
                      {selectedNotebook.analysisHistory.slice().reverse().map((h, i) => (
                        <div key={i} className="border border-[#e8e9eb] rounded-lg p-3">
                          <div className="flex justify-between text-[11px] text-[#46464a] mb-1"><span>{h.updatedAt}</span><span>{h.model}</span></div>
                          <div className="text-xs text-[#46464a] line-clamp-3"><ReactMarkdown rehypePlugins={[rehypeSanitize]}>{h.analysisMd?.slice(0, 600) + '...'}</ReactMarkdown></div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              <div className="mt-6 pt-4 border-t border-[#e8e9eb] flex flex-wrap justify-between items-center gap-3">
                <span className="text-xs text-[#46464a]">{hasIndexingSources ? 'Aguarde a indexação para atualizar.' : 'Pronto para atualizar com as fontes atuais.'}</span>
                <Tooltip content={hasIndexingSources ? `Aguarde ${selectedNotebook.sources.filter(s => s.status === 'INDEXING').length} fonte(s) finalizarem a indexação` : actionLoading ? 'Gerando análise...' : 'Gerar nova análise com o GEM'} side="top">
                  <button onClick={handleReanalyze} disabled={hasIndexingSources || actionLoading} className="inline-flex items-center gap-2 px-6 py-2.5 bg-[#191c1d] hover:bg-[#222223] text-white rounded-full text-xs font-medium disabled:opacity-40">
                    {actionLoading && <InlineSpinner size={12} light />}Atualizar pré-análise
                  </button>
                </Tooltip>
              </div>
            </div>
          </div>
        )}

        {isCreateModalOpen && (
          <div className="fixed inset-0 bg-[#191c1d]/30 backdrop-blur-sm flex items-center justify-center p-4 z-50">
            <div className="bg-white border border-[#e8e9eb] rounded-xl max-w-lg w-full p-6 shadow-[0_8px_32px_-4px_rgba(46,46,48,0.12)] max-h-[90vh] overflow-y-auto">
              <div className="flex justify-between items-center mb-4">
                <h2 className="text-base font-semibold tracking-[-0.02em] text-[#191c1d]">Criar novo caderno</h2>
                <button onClick={() => setIsCreateModalOpen(false)} className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-[#f8f9fa] text-[#46464a]">×</button>
              </div>
              <form onSubmit={handleCreateNotebook} className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-[#191c1d] mb-1">Nome do caderno</label>
                  <input type="text" required value={formTitle} onChange={(e) => setFormTitle(e.target.value)} placeholder="Ex: Onboarding Fiscal" className="w-full h-10 px-3 bg-white border border-[#e8e9eb] rounded-lg text-sm focus:outline-none focus:border-[#191c1d]" />
                </div>
                <div>
                  <label className="block text-xs font-medium text-[#191c1d] mb-1">Objetivo</label>
                  <textarea value={formObjective} onChange={(e) => setFormObjective(e.target.value)} placeholder="Descreva as dores e objetivo..." className="w-full p-3 bg-white border border-[#e8e9eb] rounded-lg text-sm h-20 resize-none focus:outline-none focus:border-[#191c1d]" />
                </div>
                <div>
                  <label className="block text-xs font-medium text-[#191c1d] mb-1">Arquivos — arraste ou selecione</label>
                  <div onDragOver={(e) => handleDragOver(e, setDragActiveCreate)} onDragLeave={(e) => handleDragLeave(e, setDragActiveCreate)} onDrop={handleDropCreate} className={`p-6 border border-dashed rounded-xl text-center ${dragActiveCreate ? 'border-[#191c1d] bg-[#f8f9fa]' : 'border-[#c7c6ca] bg-white'}`}>
                    <p className="text-xs text-[#46464a]">Arraste arquivos aqui</p>
                    <label className="inline-block mt-2 px-4 py-2 bg-[#191c1d] text-white rounded-full text-xs cursor-pointer">Selecionar arquivos<input type="file" multiple accept=".pdf,.md,.txt,.png,.jpg,.jpeg,.webp" onChange={(e) => setFiles((prev) => [...prev, ...Array.from(e.target.files || [])])} className="hidden" /></label>
                    <p className="text-[11px] text-[#a5a5ab] mt-1">PDF, MD, TXT, PNG, JPG</p>
                  </div>
                  {files.length > 0 && (
                    <div className="mt-2 space-y-1">
                      {files.map((f, idx) => (
                        <div key={`${f.name}-${idx}`} className="flex justify-between items-center bg-[#f8f9fa] border border-[#e8e9eb] px-2 py-1 rounded-lg text-xs">
                          <span className="truncate">{f.name} <span className="text-[#a5a5ab]">({(f.size / 1024).toFixed(0)} KB)</span></span>
                          <button type="button" onClick={() => removeFileAt(idx)} className="text-[#46464a] ml-2">Remover</button>
                        </div>
                      ))}
                      <button type="button" onClick={() => setFiles([])} className="text-xs text-[#46464a]">Limpar todos</button>
                    </div>
                  )}
                </div>
                <div>
                  <label className="block text-xs font-medium text-[#191c1d] mb-1">Documentação (URLs) — vírgula para vários</label>
                  <textarea value={siteUrl} onChange={(e) => setSiteUrl(e.target.value)} placeholder="https://..., https://..." className="w-full p-3 bg-white border border-[#e8e9eb] rounded-lg text-sm h-20 resize-none focus:outline-none focus:border-[#191c1d]" rows={3} />
                  {parseLinks(siteUrl).length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {parseLinks(siteUrl).map((link, idx) => (
                        <span key={idx} className="inline-flex items-center gap-1 bg-[#f8f9fa] border border-[#e8e9eb] text-xs px-2 py-1 rounded-full">
                          <span className="truncate max-w-[200px]" title={link}>{link}</span>
                          <button type="button" onClick={() => removeSiteUrlAt(idx)} className="text-[#46464a]">×</button>
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <div>
                  <label className="block text-xs font-medium text-[#191c1d] mb-1">Vídeos (YouTube) — vírgula para vários</label>
                  <textarea value={youtubeUrl} onChange={(e) => setYoutubeUrl(e.target.value)} placeholder="https://youtube.com/watch?v=..., https://youtu.be/..." className="w-full p-3 bg-white border border-[#e8e9eb] rounded-lg text-sm h-16 resize-none focus:outline-none focus:border-[#191c1d]" rows={2} />
                  {parseLinks(youtubeUrl).length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {parseLinks(youtubeUrl).map((link, idx) => (
                        <span key={idx} className="inline-flex items-center gap-1 bg-[#f8f9fa] border border-[#e8e9eb] text-xs px-2 py-1 rounded-full">
                          <span className="truncate max-w-[200px]" title={link}>{link}</span>
                          <button type="button" onClick={() => removeYoutubeUrlAt(idx)} className="text-[#46464a]">×</button>
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <div className="flex justify-end gap-2 pt-2">
                  <button type="button" onClick={() => setIsCreateModalOpen(false)} disabled={actionLoading} className="px-4 py-2 bg-white border border-[#e8e9eb] rounded-full text-xs text-[#191c1d] disabled:opacity-40">Cancelar</button>
                  <button type="submit" disabled={actionLoading} className="inline-flex items-center gap-2 px-5 py-2 bg-[#df5241] hover:bg-[#c84434] text-white rounded-full text-xs font-medium disabled:opacity-60">
                    {actionLoading && <InlineSpinner size={12} light />}{actionLoading ? 'Gerando...' : 'Gerar pré-análise'}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {isAddSourceModalOpen && (
          <div className="fixed inset-0 bg-[#191c1d]/30 backdrop-blur-sm flex items-center justify-center p-4 z-50">
            <div className="bg-white border border-[#e8e9eb] rounded-xl max-w-md w-full p-6 shadow-[0_8px_32px_-4px_rgba(46,46,48,0.12)] max-h-[90vh] overflow-y-auto">
              <div className="flex justify-between items-center mb-4">
                <h2 className="text-base font-semibold text-[#191c1d]">Adicionar fontes</h2>
                <button onClick={() => setIsAddSourceModalOpen(false)} className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-[#f8f9fa] text-[#46464a]">×</button>
              </div>
              <p className="text-xs text-[#46464a] mb-3">No caderno <span className="font-medium text-[#191c1d]">{selectedNotebook?.title}</span></p>
              <form onSubmit={handleAppendSource} className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-[#191c1d] mb-1">Arquivos</label>
                  <div onDragOver={(e) => handleDragOver(e, setDragActiveAppend)} onDragLeave={(e) => handleDragLeave(e, setDragActiveAppend)} onDrop={handleDropAppend} className={`p-6 border border-dashed rounded-xl text-center ${dragActiveAppend ? 'border-[#191c1d] bg-[#f8f9fa]' : 'border-[#c7c6ca] bg-white'}`}>
                    <p className="text-xs text-[#46464a]">Arraste arquivos aqui</p>
                    <label className="inline-block mt-2 px-4 py-2 bg-[#191c1d] text-white rounded-full text-xs cursor-pointer">Selecionar<input type="file" multiple accept=".pdf,.md,.txt,.png,.jpg,.jpeg,.webp" onChange={(e) => setFiles((prev) => [...prev, ...Array.from(e.target.files || [])])} className="hidden" /></label>
                  </div>
                  {files.length > 0 && (
                    <div className="mt-2 space-y-1">
                      {files.map((f, idx) => (
                        <div key={`${f.name}-${idx}`} className="flex justify-between items-center bg-[#f8f9fa] border border-[#e8e9eb] px-2 py-1 rounded-lg text-xs">
                          <span className="truncate">{f.name}</span>
                          <button type="button" onClick={() => removeFileAt(idx)} className="text-[#46464a]">Remover</button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <div>
                  <label className="block text-xs font-medium text-[#191c1d] mb-1">URLs de documentação — vírgula</label>
                  <textarea value={siteUrl} onChange={(e) => setSiteUrl(e.target.value)} placeholder="https://..., https://..." className="w-full p-3 bg-white border border-[#e8e9eb] rounded-lg text-sm h-20 resize-none focus:outline-none focus:border-[#191c1d]" rows={3} />
                  {parseLinks(siteUrl).length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {parseLinks(siteUrl).map((link, idx) => (
                        <span key={idx} className="inline-flex items-center gap-1 bg-[#f8f9fa] border border-[#e8e9eb] text-xs px-2 py-1 rounded-full"><span className="truncate max-w-[200px]" title={link}>{link}</span><button type="button" onClick={() => removeSiteUrlAt(idx)} className="text-[#46464a]">×</button></span>
                      ))}
                    </div>
                  )}
                </div>
                <div>
                  <label className="block text-xs font-medium text-[#191c1d] mb-1">YouTube — vírgula</label>
                  <textarea value={youtubeUrl} onChange={(e) => setYoutubeUrl(e.target.value)} placeholder="https://youtube.com/..., https://youtu.be/..." className="w-full p-3 bg-white border border-[#e8e9eb] rounded-lg text-sm h-16 resize-none focus:outline-none focus:border-[#191c1d]" rows={2} />
                  {parseLinks(youtubeUrl).length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {parseLinks(youtubeUrl).map((link, idx) => (
                        <span key={idx} className="inline-flex items-center gap-1 bg-[#f8f9fa] border border-[#e8e9eb] text-xs px-2 py-1 rounded-full"><span className="truncate max-w-[200px]" title={link}>{link}</span><button type="button" onClick={() => removeYoutubeUrlAt(idx)} className="text-[#46464a]">×</button></span>
                      ))}
                    </div>
                  )}
                </div>
                <div className="flex justify-end gap-2 pt-2">
                  <button type="button" onClick={() => setIsAddSourceModalOpen(false)} disabled={actionLoading} className="px-4 py-2 bg-white border border-[#e8e9eb] rounded-full text-xs disabled:opacity-40">Cancelar</button>
                  <button type="submit" disabled={actionLoading} className="inline-flex items-center gap-2 px-5 py-2 bg-[#df5241] hover:bg-[#c84434] text-white rounded-full text-xs font-medium disabled:opacity-60">
                    {actionLoading && <InlineSpinner size={12} light />}{actionLoading ? 'Anexando...' : 'Anexar'}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {isEditModalOpen && (
          <div className="fixed inset-0 bg-[#191c1d]/30 backdrop-blur-sm flex items-center justify-center p-4 z-50">
            <div className="bg-white border border-[#e8e9eb] rounded-xl max-w-md w-full p-6 shadow-[0_8px_32px_-4px_rgba(46,46,48,0.12)]">
              <div className="flex justify-between items-center mb-4">
                <h2 className="text-base font-semibold text-[#191c1d]">Editar caderno</h2>
                <button onClick={() => { setIsEditModalOpen(false); setEditingNotebook(null); }} className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-[#f8f9fa] text-[#46464a]">×</button>
              </div>
              <form onSubmit={handleSaveEdit} className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-[#191c1d] mb-1">Nome</label>
                  <input type="text" required value={formTitle} onChange={(e) => setFormTitle(e.target.value)} className="w-full h-10 px-3 bg-white border border-[#e8e9eb] rounded-lg text-sm focus:outline-none focus:border-[#191c1d]" />
                </div>
                <div>
                  <label className="block text-xs font-medium text-[#191c1d] mb-1">Objetivo</label>
                  <textarea value={formObjective} onChange={(e) => setFormObjective(e.target.value)} className="w-full p-3 bg-white border border-[#e8e9eb] rounded-lg text-sm h-24 resize-none focus:outline-none focus:border-[#191c1d]" />
                </div>
                <div className="flex justify-end gap-2">
                  <button type="button" onClick={() => { setIsEditModalOpen(false); setEditingNotebook(null); }} disabled={savingEdit} className="px-4 py-2 bg-white border border-[#e8e9eb] rounded-full text-xs disabled:opacity-40">Cancelar</button>
                  <button type="submit" disabled={savingEdit} className="inline-flex items-center gap-2 px-5 py-2 bg-[#191c1d] hover:bg-[#222223] text-white rounded-full text-xs font-medium disabled:opacity-60">
                    {savingEdit && <InlineSpinner size={12} light />}Salvar
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {confirmDeleteId && (
          <div className="fixed inset-0 bg-[#191c1d]/40 backdrop-blur-sm flex items-center justify-center p-4 z-[60]" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
            <div className="bg-white border border-[#e8e9eb] rounded-xl max-w-sm w-full p-6 shadow-[0_8px_32px_-4px_rgba(46,46,48,0.16)]">
              <h3 id="confirm-title" className="text-sm font-semibold text-[#191c1d]">Excluir caderno?</h3>
              <p className="mt-1 text-xs leading-5 text-[#46464a]">Essa ação remove o caderno do seu workspace e do Google NotebookLM. Não pode ser desfeita, apenas recriada.</p>
              <div className="mt-5 flex justify-end gap-2">
                <button onClick={() => setConfirmDeleteId(null)} autoFocus className="px-4 py-2 bg-white border border-[#e8e9eb] rounded-full text-xs text-[#191c1d] focus:outline-none focus:ring-2 focus:ring-[#191c1d]/20">Cancelar</button>
                <button onClick={() => { const id = confirmDeleteId; setConfirmDeleteId(null); handleDeleteNotebook(id); }} className="px-5 py-2 bg-[#ba1a1a] hover:bg-[#93000a] text-white rounded-full text-xs font-medium focus:outline-none focus:ring-2 focus:ring-[#ba1a1a]/30">Excluir</button>
              </div>
            </div>
          </div>
        )}

        {isOffline && (
          <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-40 px-4 py-2 bg-[#191c1d] text-white text-xs rounded-full shadow-lg" role="status" aria-live="polite">
            Sem conexão — alterações serão sincronizadas ao reconectar
          </div>
        )}

      </div>
    </div>
  );
}
