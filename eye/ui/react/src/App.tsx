import ChatInterface from './ChatInterface'
import ReportBuilderPanel from './ReportBuilderPanel'
import ProtocolCompliancePanel from './ProtocolCompliancePanel'
import NarrativeMap from './NarrativeMap'

function App() {
  const params = new URLSearchParams(window.location.search);
  const view = params.get('view') || 'chat';

  if (view === 'report')     return <ReportBuilderPanel />;
  if (view === 'compliance') return <ProtocolCompliancePanel />;
  if (view === 'map')        return <NarrativeMap />;

  return <ChatInterface />;
}

export default App
