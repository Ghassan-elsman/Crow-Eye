import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import { IconAlertTriangle } from './Icons';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  componentName?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error(`Uncaught error in ${this.props.componentName || 'Component'}:`, error, errorInfo);
  }

  public render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      // Check if we are in development mode (using Vite's import.meta.env or fallback)
      const isDev = (import.meta.env && import.meta.env.DEV);

      return (
        <div className="error-boundary-fallback">
          <div className="error-icon"><IconAlertTriangle size={40} /></div>
          <h3>UI Component Failure</h3>
          <p>The {this.props.componentName || 'component'} encountered a rendering error.</p>
          <button 
            className="error-retry-btn"
            onClick={() => this.setState({ hasError: false, error: null })}
          >
            Attempt Recovery
          </button>
          {isDev && (
            <details className="error-details">
              <summary>Technical Details</summary>
              <pre>{this.state.error?.toString()}</pre>
            </details>
          )}
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
