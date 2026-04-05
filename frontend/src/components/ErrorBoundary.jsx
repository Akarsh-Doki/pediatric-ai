import { Component } from 'react';

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('PediatricAI Error:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', height: '100vh', padding: '2rem',
          fontFamily: 'system-ui, sans-serif', backgroundColor: '#f8fafc',
        }}>
          <div style={{
            maxWidth: '400px', textAlign: 'center', padding: '2rem',
            borderRadius: '1rem', backgroundColor: 'white',
            boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
          }}>
            <h2 style={{ fontSize: '1.25rem', fontWeight: 600, marginBottom: '0.75rem', color: '#1a202c' }}>
              Something went wrong
            </h2>
            <p style={{ fontSize: '0.875rem', color: '#718096', marginBottom: '1.5rem', lineHeight: 1.6 }}>
              PediatricAI encountered an unexpected error. Your conversation data is safe.
            </p>
            <button
              onClick={() => window.location.reload()}
              style={{
                padding: '0.625rem 1.5rem', fontSize: '0.875rem', fontWeight: 500,
                color: 'white', backgroundColor: '#4299e1', border: 'none',
                borderRadius: '0.5rem', cursor: 'pointer',
              }}>
              Refresh Page
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}