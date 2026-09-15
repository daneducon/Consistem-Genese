import React from 'react';

export default class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { hasError: false, error: null }; }
  static getDerivedStateFromError(error) { return { hasError: true, error }; }
  componentDidCatch(error, info) { console.error('[ErrorBoundary]', error, info); }
  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen flex items-center justify-center p-6 bg-[#f8f9fa]">
          <div className="max-w-md w-full bg-white border border-[#e8e9eb] rounded-xl p-6 text-center">
            <p className="text-sm font-semibold text-[#191c1d]">Algo deu errado</p>
            <p className="text-xs text-[#46464a] mt-1">{this.state.error?.message || 'Erro inesperado na interface.'}</p>
            <button onClick={() => location.reload()} className="mt-4 px-5 py-2 bg-[#191c1d] text-white rounded-full text-xs">Recarregar</button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
