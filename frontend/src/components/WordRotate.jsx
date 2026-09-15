import React from 'react';

// Efeito estilo Magic UI WordRotate (slide vertical com pausa por palavra),
// em CSS puro para não adicionar dependências. Desenhado para exatamente
// 3 palavras: a 1ª é duplicada no fim para o loop fechar sem salto.
const DEFAULT_WORDS = ['treinamentos.', 'cursos.', 'workshops.'];

export default function WordRotate({ words = DEFAULT_WORDS, duration = 9 }) {
  const seq = [...words.slice(0, 3), words[0]];
  return (
    <span className="wr" aria-label={words[0]}>
      <span className="wr-track" aria-hidden="true" style={{ animationDuration: `${duration}s` }}>
        {seq.map((w, i) => (
          <span key={i}>{w}</span>
        ))}
      </span>
    </span>
  );
}
