import { useState } from 'react';

export default function PatientForm({ onSubmit, onCancel }) {
  const [form, setForm] = useState({ name: '', age: '', sex: 'female', weight_kg: '', known_conditions: '' });

  const handleSubmit = (e) => {
    e.preventDefault();
    onSubmit({
      name: form.name, age: parseInt(form.age), sex: form.sex,
      weight_kg: form.weight_kg ? parseFloat(form.weight_kg) : null,
      known_conditions: form.known_conditions ? form.known_conditions.split(',').map(s => s.trim()) : [],
      medications: [],
    });
  };

  const inputStyle = { backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border)', color: 'var(--text-primary)' };

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div>
        <label className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>Name</label>
        <input type="text" required value={form.name} onChange={e => setForm({...form, name: e.target.value})}
          className="w-full px-3 py-2 rounded-lg border text-sm outline-none focus:ring-2 focus:ring-blue-400" style={inputStyle} />
      </div>
      <div className="flex gap-2">
        <div className="flex-1">
          <label className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>Age</label>
          <input type="number" required min="0" max="120" value={form.age} onChange={e => setForm({...form, age: e.target.value})}
            className="w-full px-3 py-2 rounded-lg border text-sm outline-none focus:ring-2 focus:ring-blue-400" style={inputStyle} />
        </div>
        <div className="flex-1">
          <label className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>Sex</label>
          <select value={form.sex} onChange={e => setForm({...form, sex: e.target.value})}
            className="w-full px-3 py-2 rounded-lg border text-sm outline-none" style={inputStyle}>
            <option value="female">Female</option>
            <option value="male">Male</option>
          </select>
        </div>
      </div>
      <div>
        <label className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>Weight kg (optional)</label>
        <input type="number" step="0.1" min="0" value={form.weight_kg} onChange={e => setForm({...form, weight_kg: e.target.value})}
          className="w-full px-3 py-2 rounded-lg border text-sm outline-none focus:ring-2 focus:ring-blue-400" style={inputStyle} />
      </div>
      <div>
        <label className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>Known conditions (comma-separated)</label>
        <input type="text" value={form.known_conditions} onChange={e => setForm({...form, known_conditions: e.target.value})}
          placeholder="asthma, eczema"
          className="w-full px-3 py-2 rounded-lg border text-sm outline-none focus:ring-2 focus:ring-blue-400" style={inputStyle} />
      </div>
      <div className="flex gap-2 pt-2">
        <button type="submit" className="flex-1 py-2 rounded-lg text-sm font-medium text-white cursor-pointer"
          style={{ backgroundColor: 'var(--accent)' }}>Create Patient</button>
        {onCancel && <button type="button" onClick={onCancel}
          className="px-4 py-2 rounded-lg text-sm cursor-pointer"
          style={{ color: 'var(--text-secondary)', border: '1px solid var(--border)' }}>Cancel</button>}
      </div>
    </form>
  );
}