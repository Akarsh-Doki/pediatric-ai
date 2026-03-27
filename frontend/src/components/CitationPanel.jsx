import { useState } from 'react';

export default function CitationPanel({ citations }) {
  const [expanded, setExpanded] = useState(false);
  if (!citations || citations.length === 0) return null;

  return (
    <div className="mt-2">
      <button onClick={() => setExpanded(!expanded)}
        className="text-xs flex items-center gap-1 cursor-pointer"
        style={{ color: 'var(--text-secondary)' }}>
        <span>{expanded ? '▾' : '▸'}</span>
        <span>{citations.length} source{citations.length > 1 ? 's' : ''}</span>
      </button>
      {expanded && (
        <div className="mt-2 space-y-2">
          {citations.map((cite, i) => (
            <div key={i} className="p-3 rounded-lg text-xs"
              style={{ backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border)' }}>
              <div className="font-medium" style={{ color: 'var(--text-primary)' }}>{cite.doc_title}</div>
              <div style={{ color: 'var(--text-secondary)' }}>
                {cite.source}{cite.page_num && ` · p.${cite.page_num}`}
                {cite.section_type && ` · ${cite.section_type}`}
                {` · ${(cite.similarity_score * 100).toFixed(0)}% match`}
              </div>
              <div className="mt-1" style={{ color: 'var(--text-secondary)' }}>{cite.excerpt}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}