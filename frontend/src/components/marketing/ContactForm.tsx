'use client';

import { useEffect, useId, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';

import {
  CONTACT_LIMITS,
  CONTACT_TOPICS,
  contactRequestErrorMessage,
  isSelectableTopic,
  submitContactRequest,
  type ContactRequestReceipt,
  type ContactTopic,
} from '@/lib/api/contactRequests';

type Fields = {
  topic: ContactTopic;
  fullName: string;
  email: string;
  company: string;
  message: string;
  consent: boolean;
};

type FieldErrors = Partial<Record<keyof Fields, string>>;

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

const TOPIC_HINTS: Partial<Record<ContactTopic, string>> = {
  security:
    'Describe the issue and the steps to reproduce it. Do not include passwords, keys, or any customer data.',
  privacy:
    'Tell us what you are asking for (access, correction, deletion) and the email address the request is about.',
};

function validate(fields: Fields): FieldErrors {
  const errors: FieldErrors = {};
  if (!fields.fullName.trim()) errors.fullName = 'Enter your name.';
  if (!fields.email.trim()) errors.email = 'Enter your email address.';
  else if (!EMAIL.test(fields.email.trim())) errors.email = 'Enter a valid email address.';
  if (!fields.message.trim()) errors.message = 'Write your message.';
  if (!fields.consent) errors.consent = 'Tick the box so we may store and answer your message.';
  return errors;
}

const inputClass = (invalid: boolean) =>
  `w-full bg-[#0A0A0A] border ${
    invalid ? 'border-[#EF4444]' : 'border-[#262626]'
  } text-white px-4 py-3 focus:outline-none focus:border-[#10B981] focus:ring-1 focus:ring-[#10B981] transition-colors`;

/**
 * The site's contact channel. Messages are saved by the API and read by the
 * Cortex team from there; there is no mailbox behind the site.
 */
export function ContactForm() {
  const searchParams = useSearchParams();
  const requestedTopic = searchParams.get('topic');
  const ids = useId();

  const [fields, setFields] = useState<Fields>({
    topic: isSelectableTopic(requestedTopic) ? requestedTopic : 'general',
    fullName: '',
    email: '',
    company: '',
    message: '',
    consent: false,
  });
  const [errors, setErrors] = useState<FieldErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<ContactRequestReceipt | null>(null);

  // Following a "write to ..." link on this page changes ?topic= in place.
  useEffect(() => {
    if (isSelectableTopic(requestedTopic)) {
      setFields((current) => ({ ...current, topic: requestedTopic }));
    }
  }, [requestedTopic]);

  const set = <K extends keyof Fields>(key: K, value: Fields[K]) => {
    setFields((current) => ({ ...current, [key]: value }));
    if (errors[key]) {
      setErrors((current) => {
        const next = { ...current };
        delete next[key];
        return next;
      });
    }
  };

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (submitting) return;
    const found = validate(fields);
    setErrors(found);
    setFailure(null);
    if (Object.keys(found).length > 0) return;

    setSubmitting(true);
    try {
      const saved = await submitContactRequest({
        topic: fields.topic,
        full_name: fields.fullName,
        email: fields.email,
        company: fields.company,
        message: fields.message,
        consent: fields.consent,
      });
      setReceipt(saved);
    } catch (error) {
      // Keep everything the visitor typed: nothing was saved.
      setFailure(contactRequestErrorMessage(error));
    } finally {
      setSubmitting(false);
    }
  };

  if (receipt) {
    return (
      <div
        className="bg-[#111111] border border-[#262626] p-8"
        role="status"
        data-testid="contact-receipt"
      >
        <h2 className="text-xl font-medium mb-3">Your message is saved</h2>
        <p className="text-[#999999] mb-6">
          We reply to the email address you gave. Keep this reference if you need to follow up.
        </p>
        <div className="bg-[#0A0A0A] border border-[#262626] p-4 font-mono text-sm text-[#E5E5E5] inline-block">
          <span className="text-[#666666] mr-2">REFERENCE:</span>
          <span data-testid="contact-reference">{receipt.reference}</span>
        </div>
      </div>
    );
  }

  const hint = TOPIC_HINTS[fields.topic];
  const id = (name: string) => `${ids}-${name}`;

  return (
    <form
      onSubmit={onSubmit}
      noValidate
      className="bg-[#111111] border border-[#262626] p-8 space-y-6"
      data-testid="contact-form"
    >
      <div>
        <label htmlFor={id('topic')} className="block text-sm text-[#E5E5E5] mb-2 font-mono">
          Topic
        </label>
        <select
          id={id('topic')}
          name="topic"
          value={fields.topic}
          onChange={(event) => set('topic', event.target.value as ContactTopic)}
          className={inputClass(false)}
        >
          {CONTACT_TOPICS.map((topic) => (
            <option key={topic.value} value={topic.value}>
              {topic.label}
            </option>
          ))}
        </select>
        {hint && (
          <p className="text-xs text-[#999999] mt-2" data-testid="contact-topic-hint">
            {hint}
          </p>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div>
          <label htmlFor={id('name')} className="block text-sm text-[#E5E5E5] mb-2 font-mono">
            Your name
          </label>
          <input
            id={id('name')}
            name="fullName"
            type="text"
            autoComplete="name"
            maxLength={CONTACT_LIMITS.name}
            value={fields.fullName}
            onChange={(event) => set('fullName', event.target.value)}
            aria-invalid={errors.fullName ? true : undefined}
            aria-describedby={errors.fullName ? id('name-error') : undefined}
            className={inputClass(Boolean(errors.fullName))}
          />
          {errors.fullName && (
            <p id={id('name-error')} className="text-[#EF4444] text-xs mt-1">
              {errors.fullName}
            </p>
          )}
        </div>
        <div>
          <label htmlFor={id('email')} className="block text-sm text-[#E5E5E5] mb-2 font-mono">
            Email address
          </label>
          <input
            id={id('email')}
            name="email"
            type="email"
            autoComplete="email"
            maxLength={CONTACT_LIMITS.email}
            value={fields.email}
            onChange={(event) => set('email', event.target.value)}
            aria-invalid={errors.email ? true : undefined}
            aria-describedby={errors.email ? id('email-error') : undefined}
            className={inputClass(Boolean(errors.email))}
          />
          {errors.email && (
            <p id={id('email-error')} className="text-[#EF4444] text-xs mt-1">
              {errors.email}
            </p>
          )}
        </div>
      </div>

      <div>
        <label htmlFor={id('company')} className="block text-sm text-[#E5E5E5] mb-2 font-mono">
          Company (optional)
        </label>
        <input
          id={id('company')}
          name="company"
          type="text"
          autoComplete="organization"
          maxLength={CONTACT_LIMITS.company}
          value={fields.company}
          onChange={(event) => set('company', event.target.value)}
          className={inputClass(false)}
        />
      </div>

      <div>
        <label htmlFor={id('message')} className="block text-sm text-[#E5E5E5] mb-2 font-mono">
          Message
        </label>
        <textarea
          id={id('message')}
          name="message"
          rows={6}
          maxLength={CONTACT_LIMITS.message}
          value={fields.message}
          onChange={(event) => set('message', event.target.value)}
          aria-invalid={errors.message ? true : undefined}
          aria-describedby={errors.message ? id('message-error') : id('message-count')}
          className={inputClass(Boolean(errors.message))}
        />
        <div className="flex justify-between gap-4 mt-1">
          {errors.message ? (
            <p id={id('message-error')} className="text-[#EF4444] text-xs">
              {errors.message}
            </p>
          ) : (
            <span />
          )}
          <span id={id('message-count')} className="text-xs text-[#666666]">
            {fields.message.length}/{CONTACT_LIMITS.message}
          </span>
        </div>
      </div>

      <div>
        <label className="flex items-start gap-3 cursor-pointer">
          <input
            type="checkbox"
            name="consent"
            checked={fields.consent}
            onChange={(event) => set('consent', event.target.checked)}
            aria-invalid={errors.consent ? true : undefined}
            aria-describedby={errors.consent ? id('consent-error') : undefined}
            className="h-5 w-5 mt-0.5 bg-[#0A0A0A] border-[#262626] text-[#10B981] focus:ring-[#10B981] rounded-none"
          />
          <span className="text-[#999999] text-sm leading-relaxed">
            Cortex may store this message and use my details to answer it, as described in the{' '}
            <Link href="/legal/privacy" className="underline hover:text-white">
              Privacy Policy
            </Link>
            .
          </span>
        </label>
        {errors.consent && (
          <p id={id('consent-error')} className="text-[#EF4444] text-xs mt-2 ml-8">
            {errors.consent}
          </p>
        )}
      </div>

      {failure && (
        <p
          role="alert"
          className="border border-[#EF4444]/40 bg-[#EF4444]/5 text-[#FCA5A5] text-sm p-4"
          data-testid="contact-error"
        >
          {failure}
        </p>
      )}

      <div className="flex justify-end">
        <button
          type="submit"
          disabled={submitting}
          className="bg-[#10B981] hover:bg-[#059669] disabled:bg-[#10B981]/50 disabled:cursor-not-allowed text-white px-8 py-3 font-medium transition-colors"
        >
          {submitting ? 'Sending...' : 'Send message'}
        </button>
      </div>
    </form>
  );
}
