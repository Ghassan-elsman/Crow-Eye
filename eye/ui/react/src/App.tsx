import ChatInterface from './ChatInterface'
import ReportBuilderPanel from './ReportBuilderPanel'
import ProtocolCompliancePanel from './ProtocolCompliancePanel'
import NarrativeMap from './NarrativeMap'
import ImportedEvidencePanel from './ImportedEvidencePanel'

function App() {
  const params = new URLSearchParams(window.location.search);
  const view = params.get('view') || 'chat';

  if (view === 'report')     return <ReportBuilderPanel />;
  if (view === 'compliance') return <ProtocolCompliancePanel />;
  if (view === 'map')        return <NarrativeMap />;
  if (view === 'evidence')   return <ImportedEvidencePanel />;

  return <ChatInterface />;
}

export default App
