import { useCallback, useState } from 'react';
import { parseResume } from '../api/client';

interface ResumeUploadProps {
  onDone: (resumeText: string, fileB64?: string, fileType?: string, fileName?: string) => void;
}

const ResumeUpload = ({ onDone }: ResumeUploadProps) => {
  const [dragging, setDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);

  const handleFile = useCallback(
    async (file: File) => {
      const ext = file.name.toLowerCase();
      if (!ext.endsWith('.pdf') && !ext.endsWith('.tex')) {
        setError('Only PDF and LaTeX (.tex) files are supported.');
        return;
      }
      setError(null);
      setFileName(file.name);
      setLoading(true);
      try {
        const parsed = await parseResume(file);
        onDone(parsed.text, parsed.file_b64, parsed.file_type, file.name);
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : 'Upload failed.';
        setError(msg);
        setFileName(null);
      } finally {
        setLoading(false);
      }
    },
    [onDone]
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile]
  );

  const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  };

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold text-gray-800">Upload Your Resume</h2>
      <p className="text-sm text-gray-500">Supported formats: PDF or LaTeX (.tex) — max 10 MB</p>

      <label
        className={`block border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-colors
          ${dragging ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-blue-400 bg-gray-50'}`}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <input
          type="file"
          accept=".pdf,.tex,application/pdf,text/x-tex,application/x-tex"
          className="hidden"
          onChange={onInputChange}
          disabled={loading}
        />
        {loading ? (
          <div className="flex flex-col items-center gap-3 text-blue-600">
            <div className="w-8 h-8 border-4 border-blue-200 border-t-blue-600 rounded-full animate-spin" />
            <span className="text-sm font-medium">Parsing resume…</span>
          </div>
        ) : fileName ? (
          <div className="flex flex-col items-center gap-2 text-green-600">
            <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span className="text-sm font-medium">{fileName}</span>
            <span className="text-xs text-gray-400">Click or drop to replace</span>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-3 text-gray-400">
            <svg className="w-10 h-10" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round"
                d="M9 13h6m-3-3v6m5 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <span className="text-sm">
              <span className="font-medium text-blue-600">Click to upload</span> or drag and drop
            </span>
          </div>
        )}
      </label>

      {error && (
        <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-2">
          {error}
        </p>
      )}
    </div>
  );
};

export default ResumeUpload;
