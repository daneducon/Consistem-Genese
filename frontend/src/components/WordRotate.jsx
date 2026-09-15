import React, { useEffect, useState } from 'react';

// WordRotate fluido estilo Magic UI: empilha as palavras na mesma célula
// (grid) e anima com transition + cubic-bezier, sem keyframes de track.
// Isso elimina o "travamento" causado por porcentagens de translateY
// (-25%/-50%/-75%) e por easing aplicado em cima de pausas longas.
const DEFAULT_WORDS = ['treinamentos.', 'cursos.', 'workshops.'];

export default function WordRotate({ words = DEFAULT_WORDS, duration = 6 }) {
  const len = Math.max(words.length, 1);
  // duration (legado) = tempo total do ciclo em segundos -> intervalo por palavra
  const intervalMs = duration > 20 ? duration : Math.round((duration * 1000) / len);
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (len <= 1) return;
    const id = setTimeout(() => setIndex((i) => (i + 1) % len), intervalMs);
    return () => clearTimeout(id);
  }, [index, intervalMs, len]);

  const prev = (index + len - 1) % len;

  return (
    <span className="wr" aria-label={words[index]}>
      {words.map((w, i) => {
        const state = i === index ? 'wr-word is-active' : i === prev ? 'wr-word is-above' : 'wr-word is-below';
        return (
          <span key={`${w}-${i}`} aria-hidden={i !== index} className={state}>
            {w}
          </span>
        );
      })}
    </span>
  );
}
