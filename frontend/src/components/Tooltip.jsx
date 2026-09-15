import React, { useState, useId } from 'react';

export default function Tooltip({ content, children, side = 'top', disabled, maxWidth = 'max-w-[220px]' }) {
  const [visible, setVisible] = useState(false);
  const id = useId();
  if (!content) return children;

  const sideClasses = {
    top: 'bottom-full left-1/2 -translate-x-1/2 mb-2',
    bottom: 'top-full left-1/2 -translate-x-1/2 mt-2',
    left: 'right-full top-1/2 -translate-y-1/2 mr-2',
    right: 'left-full top-1/2 -translate-y-1/2 ml-2',
  }[side] || 'bottom-full left-1/2 -translate-x-1/2 mb-2';

  const arrowSide = {
    top: 'top-full left-1/2 -translate-x-1/2 border-t-[#191c1d] border-x-transparent border-b-transparent',
    bottom: 'bottom-full left-1/2 -translate-x-1/2 border-b-[#191c1d] border-x-transparent border-t-transparent',
    left: 'left-full top-1/2 -translate-y-1/2 border-l-[#191c1d] border-y-transparent border-r-transparent',
    right: 'right-full top-1/2 -translate-y-1/2 border-r-[#191c1d] border-y-transparent border-l-transparent',
  }[side];

  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
      onFocus={() => setVisible(true)}
      onBlur={() => setVisible(false)}
      aria-describedby={visible ? id : undefined}
      tabIndex={disabled ? undefined : 0}
    >
      {children}
      {visible && (
        <span
          id={id}
          role="tooltip"
          className={`absolute ${sideClasses} ${maxWidth} z-40 px-2.5 py-1.5 bg-[#191c1d] text-white text-[11px] leading-[14px] font-medium rounded-lg shadow-[0_4px_16px_rgba(0,0,0,0.12)] pointer-events-none whitespace-normal break-words text-center`}
        >
          {content}
          <span className={`absolute w-0 h-0 border-[5px] ${arrowSide}`} />
        </span>
      )}
    </span>
  );
}
