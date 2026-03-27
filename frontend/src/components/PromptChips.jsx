const SUGGESTIONS = [
  "My child has a 102°F fever and won't eat",
  "Is this rash something to worry about?",
  "Can I give Tylenol with antibiotics?",
  "When should I take my child to the ER?",
];

export default function PromptChips({ onSelect, disabled }) {
  return (
    <div className="flex flex-wrap gap-2 justify-center max-w-xl mx-auto">
      {SUGGESTIONS.map((prompt, i) => (
        <button key={i} onClick={() => onSelect(prompt)} disabled={disabled}
          className="px-4 py-2 rounded-full text-sm border transition-all duration-200 cursor-pointer hover:shadow-md disabled:opacity-50 disabled:cursor-not-allowed"
          style={{ borderColor: 'var(--border)', color: 'var(--text-secondary)', backgroundColor: 'var(--bg-secondary)' }}>
          {prompt}
        </button>
      ))}
    </div>
  );
}