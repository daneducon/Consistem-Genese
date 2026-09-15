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
        width: 320,
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
        headers: { 'Content-Type': 'application/json', ...(localStorage.getItem('genese_token') ? {} : {}) },
        credentials: 'omit',
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
    <div className="min-h-screen flex bg-white font-['DM_Sans']">
      {/* Esquerda — institucional */}
      <div className="flex-1 hidden md:flex flex-col justify-center px-12 lg:px-20 bg-white">
        <img src="/logo_genese.png" alt="Consistem Gênese" className="h-12 w-auto object-contain object-left" />
        <p className="mt-10 text-[12px] font-semibold tracking-[0.18em] text-[#d63b2f]">DIAGNÓSTICO DE T&amp;D</p>
        <h1 className="mt-4 text-[44px] lg:text-[54px] font-semibold tracking-[-0.02em] leading-[1.05] text-[#191c1d]">
          Analise cenários.<br />Estruture treinamentos.
        </h1>
        <p className="mt-5 max-w-[440px] text-[15px] leading-7 text-[#46464a]">
          Reúna PDFs, links e vídeos em um só lugar e receba diagnósticos de T&amp;D
          com roteiros de entrevista em segundos, via NotebookLM + Gemma.
        </p>
      </div>

      {/* Direita — capa + card de acesso */}
      <div className="flex-1 relative flex items-center justify-center overflow-hidden bg-[#232326] p-6 md:m-3 md:rounded-[1.5rem]">
        <img
          src="/wp-capa.jpg"
          alt=""
          className="absolute inset-0 w-full h-full object-cover opacity-35"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-[#191c1d]/85 via-[#232326]/55 to-[#232326]/35"></div>

        <div className="relative w-full max-w-[400px] bg-white rounded-[1.5rem] px-8 py-9 shadow-2xl">
          <img src="/logo_genese.png" alt="Consistem Gênese" className="h-16 w-auto object-contain" />
          <p className="mt-6 text-[11px] font-semibold tracking-[0.18em] text-[#a5a5ab]">CONSISTEM GÊNESE</p>
          <h2 className="mt-2 text-[26px] font-semibold tracking-[-0.01em] text-[#191c1d]">Bem-vindo ao Gênese</h2>
          <p className="mt-2 text-sm leading-6 text-[#46464a]">
            Acesse com sua conta Google do Workspace para ver seus cadernos.
          </p>

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

          <div className="mt-6 pt-5 border-t border-[#e8e9eb]">
            <p className="text-[11px] leading-5 text-[#a5a5ab]">
              <span className="inline-block align-[-2px] mr-1.5">🔒</span>
              O acesso é validado pela conta Google da Consistem e protegido por sessão segura.
            </p>
            <p className="mt-3 text-[10px] leading-4 text-[#c4c4c9]">
              Problemas? Verifique se o Authorized origin em Google Cloud inclui <span className="font-mono bg-[#f4f4f5] border border-[#e8e9eb] px-1 py-0.5 rounded">https://consistem-genese.vercel.app</span>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
