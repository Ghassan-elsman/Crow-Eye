import ChatInterface from './ChatInterface'
import ReportBuilderPanel from './ReportBuilderPanel'
import ProtocolCompliancePanel from './ProtocolCompliancePanel'

function App() {
  const params = new URLSearchParams(window.location.search);
  const view = params.get('view') || 'chat';

  if (view === 'report')     return <ReportBuilderPanel />;
  if (view === 'compliance') return <ProtocolCompliancePanel />;

  return <ChatInterface />;
}

export default App
