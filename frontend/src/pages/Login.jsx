import React, { useEffect, useState } from 'react';

const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_OAUTH_CLIENT_ID || '';

export default function Login({ onLogin }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) {
      setError('VITE_GOOGLE_OAUTH_CLIENT_ID não configurado. Configure no .env e na Vercel.');
      return;
    }
    const id = 'google-gsi-script';
    if (document.getElementById(id)) {
      initGsi();
      return;
    }
    const s = document.createElement('script');
    s.id = id;
    s.src = 'https://accounts.google.com/gsi/client';
    s.async = true;
    s.defer = true;
    s.onload = initGsi;
    document.head.appendChild(s);
    // eslint-disable-next-line
  }, []);

  const initGsi = () => {
    if (!window.google || !GOOGLE_CLIENT_ID) return;
    window.google.accounts.id.initialize({
      client_id: GOOGLE_CLIENT_ID,
      callback: handleCredential,
      auto_select: false,
    });
    const btn = document.getElementById('gsi-btn');
    if (btn) {
      window.google.accounts.id.renderButton(btn, {
        theme: 'outline',
        size: 'large',
        width: 360,
        text: 'signin_with',
        shape: 'pill',
      });
    }
  };

  const handleCredential = async (resp) => {
    const id_token = resp.credential;
    if (!id_token) {
      setError('Falha ao obter credencial do Google');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const r = await fetch(`${API_BASE}/api/v1/auth/google`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ id_token }),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail || 'Falha na autenticação');
      const token = j.token;
      const user = j.user;
      if (token) localStorage.setItem('genese_token', token);
      if (user) localStorage.setItem('genese_user', JSON.stringify(user));
      if (onLogin) onLogin(user, token);
    } catch (e) {
      setError(e.message || 'Erro ao autenticar');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex bg-[#f8f9fa] font-['DM_Sans']">
      {/* Esquerda — formulário */}
      <div className="flex-1 flex items-center justify-center p-6 md:p-10 bg-white">
        <div className="w-full max-w-[360px]">
          <img src="/logo_genese.png" alt="Consistem Gênese" className="h-9 w-auto object-contain" />
          <h1 className="mt-8 text-[28px] font-semibold tracking-[-0.02em] leading-none text-[#191c1d]">Bem-vindo ao Gênese</h1>
          <p className="mt-2 text-sm leading-6 text-[#46464a]">Acesse com sua conta Google do Workspace para ver seus cadernos.</p>

          {error && (
            <div className="mt-4 px-3 py-2 bg-[#ffdad6] border border-[#ffdad6] rounded-lg text-xs text-[#93000a]">{error}</div>
          )}

          <div className="mt-6">
            <div id="gsi-btn" className="flex justify-center min-h-[44px]"></div>
            {!window.google && GOOGLE_CLIENT_ID && (
              <p className="text-[11px] text-[#a5a5ab] text-center mt-2">Carregando Google Identity...</p>
            )}
            {loading && (
              <div className="mt-3 flex items-center justify-center gap-2 text-xs text-[#46464a]">
                <span className="w-4 h-4 border-2 border-[#191c1d] border-t-transparent rounded-full animate-spin"></span> Autenticando...
              </div>
            )}
          </div>

          <p className="mt-6 text-[11px] leading-4 text-[#a5a5ab] text-center">
            Ao continuar, você concorda com o uso de <span className="text-[#191c1d]">consistem.com.br</span> e com a política de dados do Workspace.
          </p>

          <p className="mt-4 text-[11px] text-[#46464a] text-center">
            Problemas? Verifique se o <span className="font-medium text-[#191c1d]">Authorized origin</span> em Google Cloud inclui <span className="font-mono text-[10px] bg-[#f8f9fa] border border-[#e8e9eb] px-1 py-0.5 rounded">https://consistem-genese.vercel.app</span>
          </p>
        </div>
      </div>

      {/* Direita — imagem institucional (oculta em mobile) */}
      <div className="hidden lg:flex flex-1 relative overflow-hidden bg-[#2e2e30] m-3 rounded-[1.5rem]">
        <img
          src="https://images.unsplash.com/photo-1551836022-deb4988cc6c0?q=80&w=1000&auto=format&fit=crop"
          alt=""
          className="absolute inset-0 w-full h-full object-cover opacity-40"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-[#191c1d]/80 via-[#2e2e30]/20 to-transparent"></div>
        <div className="relative mt-auto p-10 text-white">
          <p className="text-[22px] font-semibold leading-6 tracking-[-0.02em]">"Estamos estruturando diagnósticos de T&D com o Gênese em cada novo projeto e não imaginamos sem."</p>
          <p className="mt-4 text-xs font-medium">Consistem Gênese</p>
          <p className="text-[11px] text-white/70">Diagnóstico de T&D · NotebookLM + Gemma</p>
        </div>
      </div>
    </div>
  );
}
