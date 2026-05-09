import React from 'react';
import type { ThinkingStep } from './types';
import { StepIcon } from './Icons';
import './ThinkingTrace.css';

interface ThinkingTraceProps {
  steps: ThinkingStep[];
}

const ThinkingTrace: React.FC<ThinkingTraceProps> = ({ steps }) => {
  if (!steps || steps.length === 0) return null;

  return (
    <div className="thinking-trace" aria-label="AI processing trace">
      <div className="trace-header">
        <span className="trace-label">Processing</span>
      </div>
      <div className="trace-steps">
        {steps.map((step) => (
          <div
            key={step.step_id}
            className={`trace-step trace-step--${step.status} trace-step--${step.type}`}
          >
            <div className="trace-step-icon">
              <StepIcon type={step.type} status={step.status} size={13} />
            </div>
            <div className="trace-step-body">
              <span className="trace-step-label">{step.label}</span>
              {step.tool && step.params && (
                <div className="trace-step-params">
                  <span className="trace-tool-name">{step.tool}</span>
                  {Object.entries(step.params).map(([key, val]) => (
                    <div key={key} className="trace-param-row">
                      <span className="trace-param-key">{key}:</span>
                      <span className="trace-param-val">{String(val)}</span>
                    </div>
                  ))}
                </div>
              )}
              {step.detail && (
                <div className="trace-step-detail">{step.detail}</div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default ThinkingTrace;
