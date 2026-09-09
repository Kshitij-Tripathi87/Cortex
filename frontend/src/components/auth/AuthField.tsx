/**
 * Labelled input with per-field error slot. Controlled by the page.
 */

import React from "react";

interface AuthFieldProps extends React.InputHTMLAttributes<HTMLInputElement> {
  id: string;
  label: string;
  error?: string;
  hint?: string;
}

export function AuthField({ id, label, error, hint, ...inputProps }: AuthFieldProps): React.JSX.Element {
  return (
    <div>
      <label htmlFor={id} className="block text-xs font-medium text-ink-secondary mb-1.5">
        {label}
      </label>
      <input
        id={id}
        {...inputProps}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined}
        className="w-full bg-bg border border-border-strong px-3 py-2 text-sm text-ink outline-none placeholder:text-ink-muted focus:border-accent disabled:opacity-50"
      />
      {error ? (
        <p id={`${id}-error`} role="alert" className="text-xs text-critical mt-1.5">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="text-xs text-ink-muted mt-1.5">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
