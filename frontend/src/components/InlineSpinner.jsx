import React from 'react';

export default function InlineSpinner({ size = 14, light = false, className = '' }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block border-2 rounded-full animate-spin shrink-0 ${light ? 'border-white border-t-transparent' : 'border-[#191c1d] border-t-transparent'} ${className}`}
      style={{ width: size, height: size }}
    />
  );
}
