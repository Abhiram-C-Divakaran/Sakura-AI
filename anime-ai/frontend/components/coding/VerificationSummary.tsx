import React from 'react';
import { ShieldCheck, ShieldAlert, CheckCircle2, XCircle, Clock } from 'lucide-react';

export interface VerificationResult {
  passed: boolean;
  totalTests?: number;
  passedTests?: number;
  failedTests?: number;
  skippedTests?: number;
  durationMs?: number;
  command?: string;
  summary?: string;
  failures?: Array<{
    testName: string;
    message: string;
  }>;
}

export interface VerificationSummaryProps {
  result?: VerificationResult;
}

export const VerificationSummary: React.FC<VerificationSummaryProps> = ({ result }) => {
  if (!result) return null;

  const isSuccess = result.passed;

  return (
    <div
      className={`rounded-xl border p-3.5 my-3 text-xs ${
        isSuccess
          ? 'border-emerald-500/20 bg-emerald-950/10 text-emerald-300'
          : 'border-rose-500/20 bg-rose-950/10 text-rose-300'
      }`}
    >
      <div className="flex items-center justify-between pb-2 border-b border-white/5">
        <div className="flex items-center gap-2">
          {isSuccess ? (
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
          ) : (
            <ShieldAlert className="w-4 h-4 text-rose-400" />
          )}
          <span className="font-semibold text-sm">
            {isSuccess ? 'Verification Passed' : 'Verification Failed'}
          </span>
        </div>

        {result.durationMs !== undefined && (
          <div className="flex items-center gap-1 text-[11px] text-neutral-400 font-mono">
            <Clock className="w-3 h-3" />
            <span>{(result.durationMs / 1000).toFixed(2)}s</span>
          </div>
        )}
      </div>

      <div className="mt-2.5 flex items-center gap-4 text-neutral-300 font-mono text-[11px]">
        {result.totalTests !== undefined && (
          <span>Total: <strong className="text-white">{result.totalTests}</strong></span>
        )}
        {result.passedTests !== undefined && (
          <span className="flex items-center gap-1 text-emerald-400">
            <CheckCircle2 className="w-3 h-3" />
            {result.passedTests} passed
          </span>
        )}
        {(result.failedTests !== undefined && result.failedTests > 0) && (
          <span className="flex items-center gap-1 text-rose-400">
            <XCircle className="w-3 h-3" />
            {result.failedTests} failed
          </span>
        )}
      </div>

      {result.summary && (
        <p className="mt-2 text-neutral-400 text-[11px] leading-relaxed">
          {result.summary}
        </p>
      )}

      {result.failures && result.failures.length > 0 && (
        <div className="mt-3 space-y-1.5 pt-2 border-t border-rose-900/30">
          <div className="text-[10px] uppercase tracking-wider text-rose-400 font-semibold">Failures</div>
          {result.failures.map((f, idx) => (
            <div key={idx} className="p-2 bg-rose-950/30 rounded border border-rose-900/30 font-mono text-[11px]">
              <div className="font-medium text-rose-200">{f.testName}</div>
              <div className="text-rose-400/90 whitespace-pre-wrap mt-0.5">{f.message}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
