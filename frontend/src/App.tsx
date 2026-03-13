import { useState } from 'react';
import StepIndicator from './components/StepIndicator';
import ResumeUpload from './components/ResumeUpload';
import JDInput from './components/JDInput';
import ResumePreview from './components/ResumePreview';
import { generateResume } from './api/client';
import type { ResumeData } from './types/resume';

const STEPS = ['Upload Resume', 'Job Description', 'Generate', 'Preview'];

type Step = 1 | 2 | 3 | 4;

export default function App() {
  const [step, setStep] = useState<Step>(1);
  const [resumeText, setResumeText] = useState('');
  const [jdText, setJdText] = useState('');
  const [generatedResume, setGeneratedResume] = useState<ResumeData | null>(null);
  const [genError, setGenError] = useState<string | null>(null);

  const handleResumeUploaded = (text: string) => {
    setResumeText(text);
    setStep(2);
  };

  const handleJdReady = async (jd: string) => {
    setJdText(jd);
    setGenError(null);
    setStep(3);

    try {
      const data = await generateResume(resumeText, jd);
      setGeneratedResume(data);
      setStep(4);
    } catch (e: unknown) {
      setGenError(e instanceof Error ? e.message : 'Generation failed.');
      setStep(2);
    }
  };

  const handleStartOver = () => {
    setStep(1);
    setResumeText('');
    setJdText('');
    setGeneratedResume(null);
    setGenError(null);
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 flex flex-col">
      <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-3 shadow-sm">
        <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
          <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round"
              d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
        </div>
        <span className="text-lg font-bold text-gray-800">pass-ats</span>
        <span className="text-xs text-gray-400 ml-1">AI Resume Tailor</span>
      </header>

      <main className="flex-1 flex flex-col items-center py-10 px-4">
        <div className="w-full max-w-2xl">
          <StepIndicator currentStep={step} steps={STEPS} />

          <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-8">
            {step === 1 && <ResumeUpload onDone={handleResumeUploaded} />}

            {step === 2 && (
              <div className="space-y-4">
                <JDInput onDone={handleJdReady} />
                {genError && (
                  <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-2">
                    {genError}
                  </p>
                )}
              </div>
            )}

            {step === 3 && (
              <div className="flex flex-col items-center gap-6 py-10">
                <div className="w-14 h-14 border-4 border-blue-200 border-t-blue-600 rounded-full animate-spin" />
                <div className="text-center space-y-1">
                  <p className="font-semibold text-gray-800">Tailoring your resume&hellip;</p>
                  <p className="text-sm text-gray-500">Groq AI is analysing the job description and optimising your resume for ATS.</p>
                </div>
              </div>
            )}

            {step === 4 && generatedResume && (
              <ResumePreview resume={generatedResume} onStartOver={handleStartOver} />
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
