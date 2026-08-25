/**
 * Error state component — displays error with optional retry button.
 */

import { ApiError } from "@/lib/api";

interface ErrorStateProps {
  error: Error | ApiError | unknown;
  onRetry?: () => void;
}

export function ErrorState({ error, onRetry }: ErrorStateProps) {
  const isApiError = error instanceof ApiError;
  const status = isApiError ? error.status : undefined;
  const detail = error instanceof Error ? error.message : "An unknown error occurred";
  const requestId = isApiError ? error.requestId : undefined;

  return (
    <div className="flex flex-col items-center justify-center py-12">
      <div className="bg-red-50 border border-red-200 rounded-lg p-6 max-w-md w-full">
        <div className="flex items-center mb-3">
          <svg
            className="w-5 h-5 text-red-500 mr-2"
            fill="currentColor"
            viewBox="0 0 20 20"
          >
            <path
              fillRule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
              clipRule="evenodd"
            />
          </svg>
          <h3 className="text-lg font-semibold text-red-900">
            {status ? `Error ${status}` : "Error"}
          </h3>
        </div>
        <p className="text-sm text-red-700 mb-3">{detail}</p>
        {requestId && (
          <p className="text-xs text-red-500 mb-3 font-mono">
            Request ID: {requestId}
          </p>
        )}
        {onRetry && (
          <button
            onClick={onRetry}
            className="px-4 py-2 bg-red-600 text-white text-sm rounded hover:bg-red-700 transition-colors"
          >
            Retry
          </button>
        )}
      </div>
    </div>
  );
}
