'use client';

import { useState } from 'react';
import Link from 'next/link';

type Step = 1 | 2;

export default function DemoPage() {
  const [step, setStep] = useState<Step>(1);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSubmitted, setIsSubmitted] = useState(false);
  const [refId, setRefId] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});

  // Form State
  const [formData, setFormData] = useState({
    // Step 1
    fullName: '',
    workEmail: '',
    company: '',
    jobTitle: '',
    primaryRole: '',
    country: '',
    companySize: '',
    // Step 2
    challenges: [] as string[],
    decisionDescription: '',
    currentSystems: [] as string[],
    desiredOutcome: '',
    timeline: '',
    consent: false,
  });

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
    // Clear error when typing
    if (errors[name]) {
      setErrors((prev) => {
        const newErrors = { ...prev };
        delete newErrors[name];
        return newErrors;
      });
    }
  };

  const handleCheckboxChange = (name: 'challenges' | 'currentSystems', value: string) => {
    setFormData((prev) => {
      const current = prev[name];
      const updated = current.includes(value) 
        ? current.filter(item => item !== value)
        : [...current, value];
      return { ...prev, [name]: updated };
    });
  };

  const validateStep1 = () => {
    const newErrors: Record<string, string> = {};
    if (!formData.fullName) newErrors.fullName = 'Required';
    if (!formData.workEmail) newErrors.workEmail = 'Required';
    else if (!/^\S+@\S+\.\S+$/.test(formData.workEmail)) newErrors.workEmail = 'Invalid email format';
    if (!formData.company) newErrors.company = 'Required';
    if (!formData.jobTitle) newErrors.jobTitle = 'Required';
    if (!formData.primaryRole) newErrors.primaryRole = 'Required';
    if (!formData.country) newErrors.country = 'Required';
    
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const validateStep2 = () => {
    const newErrors: Record<string, string> = {};
    if (!formData.decisionDescription) newErrors.decisionDescription = 'Required';
    if (!formData.consent) newErrors.consent = 'You must agree to proceed';
    
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleNext = () => {
    if (validateStep1()) {
      setStep(2);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validateStep2()) return;
    
    setIsSubmitting(true);
    
    // Simulate API call
    setTimeout(() => {
      setIsSubmitting(false);
      setRefId(`REQ-${Math.floor(Math.random() * 1000000).toString().padStart(6, '0')}`);
      setIsSubmitted(true);
    }, 1500);
  };

  if (isSubmitted) {
    return (
      <div className="min-h-screen bg-[#0A0A0A] text-white py-24 md:py-32">
        <main className="max-w-2xl mx-auto px-6">
          <div className="bg-[#111111] border border-[#262626] p-12 text-center">
            <div className="w-16 h-16 bg-[#141414] border border-[#10B981] text-[#10B981] rounded-none flex items-center justify-center mx-auto mb-6">
              <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="square" strokeLinejoin="miter" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <h1 className="text-3xl font-medium mb-4">Your request was received</h1>
            <p className="text-[#999999] mb-8">
              We have securely logged your briefing request. Our evaluation team will review the submitted criteria and contact you regarding qualification status.
            </p>
            <div className="bg-[#0A0A0A] border border-[#262626] p-4 font-mono text-sm text-[#E5E5E5] inline-block">
              <span className="text-[#666666] mr-2">REFERENCE ID:</span>
              {refId}
            </div>
            <div className="mt-12">
              <Link href="/" className="text-[#10B981] hover:text-[#059669] text-sm tracking-wider uppercase font-mono">
                Return to home
              </Link>
            </div>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white">
      <main className="max-w-[1440px] mx-auto px-6 md:px-12 py-24">
        <div className="max-w-3xl mx-auto">
          
          <div className="mb-12">
            <div className="font-mono text-[#10B981] text-xs uppercase tracking-widest mb-6 border-l-2 border-[#10B981] pl-4">
              CORTEX / DESIGN PARTNER
            </div>
            <h1 className="text-4xl font-medium tracking-tight mb-4">
              See what Cortex could do for your operation.
            </h1>
            <p className="text-[#999999]">
              To ensure alignment between your operational needs and our current capabilities, please provide context on your environment.
              Information is handled per our <Link href="#" className="underline hover:text-white">Privacy Policy</Link>.
            </p>
          </div>

          <div className="mb-8 flex gap-2 items-center font-mono text-sm">
            <div className={`px-3 py-1 ${step === 1 ? 'bg-[#10B981] text-[#0A0A0A]' : 'bg-[#1A1A1A] text-[#999999]'}`}>
              STEP 01
            </div>
            <div className="h-px bg-[#262626] w-8"></div>
            <div className={`px-3 py-1 ${step === 2 ? 'bg-[#10B981] text-[#0A0A0A]' : 'bg-[#1A1A1A] text-[#999999]'}`}>
              STEP 02
            </div>
          </div>

          <form onSubmit={handleSubmit} className="bg-[#111111] border border-[#262626] p-8 md:p-12">
            
            {step === 1 && (
              <div className="space-y-6 animate-in fade-in duration-300">
                <h2 className="text-xl font-medium mb-6 pb-4 border-b border-[#262626]">Applicant Information</h2>
                
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div>
                    <label className="block text-sm text-[#E5E5E5] mb-2 font-mono">Full Name</label>
                    <input 
                      type="text" name="fullName" value={formData.fullName} onChange={handleInputChange}
                      className={`w-full bg-[#0A0A0A] border ${errors.fullName ? 'border-[#EF4444]' : 'border-[#262626]'} text-white px-4 py-3 focus:outline-none focus:border-[#10B981] focus:ring-1 focus:ring-[#10B981]`} 
                    />
                    {errors.fullName && <div className="text-[#EF4444] text-xs mt-1">{errors.fullName}</div>}
                  </div>
                  <div>
                    <label className="block text-sm text-[#E5E5E5] mb-2 font-mono">Work Email</label>
                    <input 
                      type="email" name="workEmail" value={formData.workEmail} onChange={handleInputChange}
                      className={`w-full bg-[#0A0A0A] border ${errors.workEmail ? 'border-[#EF4444]' : 'border-[#262626]'} text-white px-4 py-3 focus:outline-none focus:border-[#10B981] focus:ring-1 focus:ring-[#10B981]`} 
                    />
                    {errors.workEmail && <div className="text-[#EF4444] text-xs mt-1">{errors.workEmail}</div>}
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div>
                    <label className="block text-sm text-[#E5E5E5] mb-2 font-mono">Company</label>
                    <input 
                      type="text" name="company" value={formData.company} onChange={handleInputChange}
                      className={`w-full bg-[#0A0A0A] border ${errors.company ? 'border-[#EF4444]' : 'border-[#262626]'} text-white px-4 py-3 focus:outline-none focus:border-[#10B981] focus:ring-1 focus:ring-[#10B981]`} 
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-[#E5E5E5] mb-2 font-mono">Job Title</label>
                    <input 
                      type="text" name="jobTitle" value={formData.jobTitle} onChange={handleInputChange}
                      className={`w-full bg-[#0A0A0A] border ${errors.jobTitle ? 'border-[#EF4444]' : 'border-[#262626]'} text-white px-4 py-3 focus:outline-none focus:border-[#10B981] focus:ring-1 focus:ring-[#10B981]`} 
                    />
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div>
                    <label className="block text-sm text-[#E5E5E5] mb-2 font-mono">Primary Role</label>
                    <select 
                      name="primaryRole" value={formData.primaryRole} onChange={handleInputChange}
                      className={`w-full bg-[#0A0A0A] border ${errors.primaryRole ? 'border-[#EF4444]' : 'border-[#262626]'} text-white px-4 py-3 focus:outline-none focus:border-[#10B981] focus:ring-1 focus:ring-[#10B981] appearance-none`}
                    >
                      <option value="">Select role...</option>
                      <option value="operations">Operations / Supply Chain</option>
                      <option value="engineering">Engineering / IT</option>
                      <option value="executive">Executive Management</option>
                      <option value="other">Other</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm text-[#E5E5E5] mb-2 font-mono">Country / Region</label>
                    <input 
                      type="text" name="country" value={formData.country} onChange={handleInputChange}
                      className={`w-full bg-[#0A0A0A] border ${errors.country ? 'border-[#EF4444]' : 'border-[#262626]'} text-white px-4 py-3 focus:outline-none focus:border-[#10B981] focus:ring-1 focus:ring-[#10B981]`} 
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-sm text-[#E5E5E5] mb-2 font-mono">Company Size (Optional)</label>
                  <select 
                    name="companySize" value={formData.companySize} onChange={handleInputChange}
                    className="w-full bg-[#0A0A0A] border border-[#262626] text-white px-4 py-3 focus:outline-none focus:border-[#10B981] focus:ring-1 focus:ring-[#10B981] appearance-none"
                  >
                    <option value="">Select band...</option>
                    <option value="1-500">1 - 500 employees</option>
                    <option value="501-2000">501 - 2,000 employees</option>
                    <option value="2001-10000">2,001 - 10,000 employees</option>
                    <option value="10000+">10,000+ employees</option>
                  </select>
                </div>

                <div className="pt-8 flex justify-end">
                  <button 
                    type="button" 
                    onClick={handleNext}
                    className="bg-[#10B981] hover:bg-[#059669] text-white px-8 py-3 font-medium transition-colors"
                  >
                    Continue to Context
                  </button>
                </div>
              </div>
            )}

            {step === 2 && (
              <div className="space-y-8 animate-in fade-in duration-300">
                <h2 className="text-xl font-medium mb-6 pb-4 border-b border-[#262626]">Operational Context</h2>
                
                <div>
                  <label className="block text-sm text-[#E5E5E5] mb-4 font-mono">1. Primary Challenge Categories</label>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {['Supplier Disruption', 'Inventory Risk', 'Logistics/Transport Disruption', 'Production Disruption', 'Demand/Market Shock', 'Other'].map(opt => (
                      <label key={opt} className="flex items-center space-x-3 cursor-pointer group">
                        <input 
                          type="checkbox" 
                          checked={formData.challenges.includes(opt)}
                          onChange={() => handleCheckboxChange('challenges', opt)}
                          className="form-checkbox h-5 w-5 bg-[#0A0A0A] border-[#262626] text-[#10B981] focus:ring-[#10B981] focus:ring-offset-0 focus:ring-offset-[#0A0A0A] rounded-none" 
                        />
                        <span className="text-[#999999] group-hover:text-white transition-colors">{opt}</span>
                      </label>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="block text-sm text-[#E5E5E5] mb-2 font-mono">2. Describe the decision workflows you are evaluating</label>
                  <div className="text-xs text-[#EF4444] mb-2 border border-[#EF4444]/30 bg-[#EF4444]/5 p-2 inline-block">
                    WARNING: Do not include PII, PHI, proprietary source code, or sensitive financial data.
                  </div>
                  <textarea 
                    name="decisionDescription" 
                    value={formData.decisionDescription} 
                    onChange={handleInputChange}
                    rows={4}
                    maxLength={1000}
                    placeholder="e.g., We need to evaluate logistics rerouting options when primary ports face congestion..."
                    className={`w-full bg-[#0A0A0A] border ${errors.decisionDescription ? 'border-[#EF4444]' : 'border-[#262626]'} text-white px-4 py-3 focus:outline-none focus:border-[#10B981] focus:ring-1 focus:ring-[#10B981]`} 
                  />
                  <div className="text-right text-xs text-[#666666] mt-1">{formData.decisionDescription.length}/1000</div>
                </div>

                <div>
                  <label className="block text-sm text-[#E5E5E5] mb-4 font-mono">3. Current Systems in Use</label>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    {['ERP Systems', 'Custom Internal DBs', 'WMS/TMS', 'BI/Analytics Dashboards', 'Spreadsheets'].map(opt => (
                      <label key={opt} className="flex items-center space-x-3 cursor-pointer group">
                        <input 
                          type="checkbox" 
                          checked={formData.currentSystems.includes(opt)}
                          onChange={() => handleCheckboxChange('currentSystems', opt)}
                          className="form-checkbox h-4 w-4 bg-[#0A0A0A] border-[#262626] text-[#10B981] focus:ring-[#10B981] rounded-none" 
                        />
                        <span className="text-[#999999] text-sm group-hover:text-white">{opt}</span>
                      </label>
                    ))}
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div>
                    <label className="block text-sm text-[#E5E5E5] mb-2 font-mono">Desired Outcome / Goal</label>
                    <input 
                      type="text" name="desiredOutcome" value={formData.desiredOutcome} onChange={handleInputChange}
                      className="w-full bg-[#0A0A0A] border border-[#262626] text-white px-4 py-3 focus:outline-none focus:border-[#10B981] focus:ring-1 focus:ring-[#10B981]" 
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-[#E5E5E5] mb-2 font-mono">Expected Timeline</label>
                    <select 
                      name="timeline" value={formData.timeline} onChange={handleInputChange}
                      className="w-full bg-[#0A0A0A] border border-[#262626] text-white px-4 py-3 focus:outline-none focus:border-[#10B981] focus:ring-1 focus:ring-[#10B981] appearance-none"
                    >
                      <option value="">Select timeframe...</option>
                      <option value="immediate">Immediate (0-1 months)</option>
                      <option value="short">Short term (1-3 months)</option>
                      <option value="medium">Medium term (3-6 months)</option>
                      <option value="exploratory">Exploratory (6+ months)</option>
                    </select>
                  </div>
                </div>

                <div className="pt-6 border-t border-[#262626]">
                  <label className="flex items-start space-x-3 cursor-pointer">
                    <input 
                      type="checkbox" 
                      name="consent"
                      checked={formData.consent}
                      onChange={(e) => {
                        setFormData(prev => ({...prev, consent: e.target.checked}));
                        if (errors.consent) setErrors(prev => ({...prev, consent: ''}));
                      }}
                      className="form-checkbox h-5 w-5 mt-1 bg-[#0A0A0A] border-[#262626] text-[#10B981] focus:ring-[#10B981] rounded-none" 
                    />
                    <span className="text-[#999999] text-sm leading-relaxed">
                      I confirm that the information provided is accurate and does not include highly restricted or classified data. I authorize Cortex to process this information to evaluate applicability.
                    </span>
                  </label>
                  {errors.consent && <div className="text-[#EF4444] text-xs mt-2 ml-8">{errors.consent}</div>}
                </div>

                <div className="pt-4 flex justify-between items-center">
                  <button 
                    type="button" 
                    onClick={() => setStep(1)}
                    className="text-[#999999] hover:text-white font-mono text-sm tracking-wider uppercase"
                  >
                    ← Back
                  </button>
                  <button 
                    type="submit" 
                    disabled={isSubmitting}
                    className="bg-[#10B981] hover:bg-[#059669] disabled:bg-[#10B981]/50 disabled:cursor-not-allowed text-white px-8 py-3 font-medium transition-colors"
                  >
                    {isSubmitting ? 'Submitting...' : 'Submit Request'}
                  </button>
                </div>
              </div>
            )}
          </form>

        </div>
      </main>
    </div>
  );
}
