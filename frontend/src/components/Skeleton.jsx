import React from 'react';

export function GridSkeleton({ count = 6 }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6" aria-busy="true" aria-label="Carregando cadernos">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="bg-white border border-[#e8e9eb] rounded-xl p-6 shadow-[0_4px_20px_-2px_rgba(46,46,48,0.04)] flex flex-col min-h-[180px] animate-pulse">
          <div className="flex justify-between items-start gap-2">
            <div className="flex-1 space-y-2">
              <div className="h-4 bg-[#f1f3f5] rounded-lg w-[85%] skeleton-shimmer" />
              <div className="h-4 bg-[#f1f3f5] rounded-lg w-[60%] skeleton-shimmer" />
            </div>
            <div className="w-6 h-6 bg-[#f1f3f5] rounded-full shrink-0 skeleton-shimmer" />
          </div>
          <div className="mt-4 space-y-2">
            <div className="h-3 bg-[#f1f3f5] rounded-full w-full skeleton-shimmer" />
            <div className="h-3 bg-[#f1f3f5] rounded-full w-[75%] skeleton-shimmer" />
          </div>
          <div className="mt-auto pt-4 flex justify-between items-center">
            <div className="h-3 w-16 bg-[#f1f3f5] rounded-full skeleton-shimmer" />
            <div className="h-3 w-20 bg-[#f1f3f5] rounded-full skeleton-shimmer" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function SourcesSkeleton({ rows = 4 }) {
  return (
    <div className="mt-4 space-y-2" aria-busy="true" aria-label="Carregando fontes">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="px-3 py-2.5 bg-white border border-[#e8e9eb] rounded-lg flex justify-between items-center gap-2 animate-pulse">
          <div className="h-3 bg-[#f1f3f5] rounded-full w-[60%] skeleton-shimmer" />
          <div className="h-5 w-16 bg-[#f1f3f5] rounded-full skeleton-shimmer" />
        </div>
      ))}
    </div>
  );
}

export function MarkdownSkeleton() {
  return (
    <div className="space-y-4 animate-pulse" aria-busy="true" aria-label="Carregando análise">
      <div className="h-6 bg-[#f1f3f5] rounded-lg w-[55%] skeleton-shimmer" />
      <div className="space-y-2">
        <div className="h-3 bg-[#f1f3f5] rounded-full w-full skeleton-shimmer" />
        <div className="h-3 bg-[#f1f3f5] rounded-full w-full skeleton-shimmer" />
        <div className="h-3 bg-[#f1f3f5] rounded-full w-[80%] skeleton-shimmer" />
      </div>
      <div className="h-5 bg-[#f1f3f5] rounded-lg w-[40%] mt-6 skeleton-shimmer" />
      <div className="space-y-2">
        <div className="flex gap-2 items-center"><div className="w-1.5 h-1.5 bg-[#e8e9eb] rounded-full" /><div className="h-3 bg-[#f1f3f5] rounded-full w-[90%] skeleton-shimmer" /></div>
        <div className="flex gap-2 items-center"><div className="w-1.5 h-1.5 bg-[#e8e9eb] rounded-full" /><div className="h-3 bg-[#f1f3f5] rounded-full w-[85%] skeleton-shimmer" /></div>
        <div className="flex gap-2 items-center"><div className="w-1.5 h-1.5 bg-[#e8e9eb] rounded-full" /><div className="h-3 bg-[#f1f3f5] rounded-full w-[70%] skeleton-shimmer" /></div>
      </div>
      <div className="h-5 bg-[#f1f3f5] rounded-lg w-[35%] mt-6 skeleton-shimmer" />
      <div className="space-y-2">
        <div className="h-3 bg-[#f1f3f5] rounded-full w-full skeleton-shimmer" />
        <div className="h-3 bg-[#f1f3f5] rounded-full w-[90%] skeleton-shimmer" />
      </div>
    </div>
  );
}
