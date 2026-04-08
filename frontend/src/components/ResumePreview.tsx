import type { ResumeData } from '../types/resume';
import { useState, useMemo } from 'react';

interface ResumePreviewProps {
  resume: ResumeData;
  onStartOver: () => void;
  rewrittenFileB64: string;
  originalFileName?: string;
}

interface ScoreBadgeProps {
  score: number;
  scoreBefore?: number | null;
}

type ScoreTier = 'excellent' | 'strong' | 'moderate' | 'weak';

const getScoreTier = (score: number): ScoreTier => {
  if (score >= 90) return 'excellent';
  if (score >= 70) return 'strong';
  if (score >= 50) return 'moderate';
  return 'weak';
};

const SCORE_TIER_STYLES: Record<ScoreTier, { container: string; bar: string; label: string }> = {
  excellent: { container: 'text-green-700 bg-green-50 border-green-200', bar: 'bg-green-500', label: 'Excellent' },
  strong:    { container: 'text-blue-700 bg-blue-50 border-blue-200',   bar: 'bg-blue-500',  label: 'Strong' },
  moderate:  { container: 'text-yellow-700 bg-yellow-50 border-yellow-200', bar: 'bg-yellow-400', label: 'Moderate' },
  weak:      { container: 'text-red-700 bg-red-50 border-red-200',       bar: 'bg-red-500',   label: 'Weak' },
};

const ScoreBadge = ({ score, scoreBefore }: ScoreBadgeProps) => {
  const tier = getScoreTier(score);
  const { container, bar, label } = SCORE_TIER_STYLES[tier];

  return (
    <div className={`rounded-xl border p-4 ${container}`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-semibold">ATS Match Score</span>
        <span className="text-2xl font-bold">{score}%</span>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-2 mb-1">
        <div className={`h-2 rounded-full transition-all ${bar}`} style={{ width: `${score}%` }} />
      </div>
      <p className="text-xs mt-1 opacity-75">{label} — resume keyword coverage against the job description</p>
      {scoreBefore != null && (
        <div className="flex items-center gap-3 mt-3 pt-3 border-t border-current/10 text-sm">
          <div className="flex items-center gap-1.5">
            <span className="opacity-75">Before:</span>
            <span className="font-semibold">{scoreBefore}%</span>
          </div>
          <span className="opacity-50">&rarr;</span>
          <div className="flex items-center gap-1.5">
            <span className="opacity-75">After:</span>
            <span className="font-semibold">{score}%</span>
          </div>
          <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
            score - scoreBefore > 0
              ? 'bg-green-100 text-green-700'
              : 'bg-gray-100 text-gray-500'
          }`}>
            {score - scoreBefore > 0 ? '+' : ''}{score - scoreBefore}%
          </span>
        </div>
      )}
    </div>
  );
};

const ResumePreview = ({ resume, onStartOver, rewrittenFileB64, originalFileName }: ResumePreviewProps) => {
  const [dlError, setDlError] = useState<string | null>(null);

  // Convert base64 PDF to a blob URL for iframe preview
  const pdfBlobUrl = useMemo(() => {
    try {
      const byteChars = atob(rewrittenFileB64);
      const byteArray = new Uint8Array(byteChars.length);
      for (let i = 0; i < byteChars.length; i++) {
        byteArray[i] = byteChars.charCodeAt(i);
      }
      const blob = new Blob([byteArray], { type: 'application/pdf' });
      return URL.createObjectURL(blob);
    } catch {
      return null;
    }
  }, [rewrittenFileB64]);

  const handleDownload = () => {
    setDlError(null);
    try {
      const byteChars = atob(rewrittenFileB64);
      const byteArray = new Uint8Array(byteChars.length);
      for (let i = 0; i < byteChars.length; i++) {
        byteArray[i] = byteChars.charCodeAt(i);
      }
      const blob = new Blob([byteArray], { type: 'application/pdf' });
      const url = URL.createObjectURL(blob);
      const baseName = resume.name
        || (originalFileName ? originalFileName.replace(/\.[^.]+$/, '') : '')
        || 'resume';
      const safeName = baseName.replace(/\s+/g, '_');
      const a = document.createElement('a');
      a.href = url;
      a.download = `${safeName}_tailored.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: unknown) {
      setDlError(e instanceof Error ? e.message : 'Download failed.');
    }
  };

  return (
    <div className="space-y-6">
      {/* Action bar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold text-gray-800">Your Tailored Resume</h2>
        <div className="flex gap-2">
          <button
            onClick={onStartOver}
            className="px-4 py-2 rounded-xl border border-gray-300 text-sm text-gray-600 hover:bg-gray-50 transition-colors"
          >
            Start Over
          </button>
          <button
            onClick={handleDownload}
            className="px-4 py-2 rounded-xl bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 transition-colors flex items-center gap-2"
          >
            Download PDF
          </button>
        </div>
      </div>

      {dlError && (
        <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-2">
          {dlError}
        </p>
      )}

      {/* ATS Score panel */}
      {resume.ats_score != null && (
        <div className="space-y-3">
          <ScoreBadge score={resume.ats_score} scoreBefore={resume.ats_score_before} />
          {resume.matched_keywords && resume.matched_keywords.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Matched Keywords</p>
              <div className="flex flex-wrap gap-1.5">
                {resume.matched_keywords.map((kw) => (
                  <span key={kw} className="px-2 py-0.5 bg-green-50 text-green-700 text-xs rounded-full border border-green-200">
                    {kw}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* PDF preview */}
      {pdfBlobUrl ? (
        <iframe
          src={pdfBlobUrl}
          title="Tailored Resume Preview"
          className="w-full border border-gray-200 rounded-2xl shadow-sm"
          style={{ height: '80vh', minHeight: '600px' }}
        />
      ) : (
        <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-2">
          Unable to render PDF preview.
        </p>
      )}
    </div>
  );
};

export default ResumePreview;
