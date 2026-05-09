import ChatInterface from './ChatInterface'
import ReportBuilderPanel from './ReportBuilderPanel'

function App() {
  const params = new URLSearchParams(window.location.search);
  const view = params.get('view') || 'chat';
  
  if (view === 'report') {
    return <ReportBuilderPanel />;
  }
  
  return <ChatInterface />;
}

export default App
