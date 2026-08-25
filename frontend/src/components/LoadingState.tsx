/**
 * Loading state component — spinner with optional message.
 */

interface LoadingStateProps {
  message?: string;
}

export function LoadingState({ message = "Loading..." }: LoadingStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-12">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mb-4" />
      <p className="text-gray-500 text-sm">{message}</p>
    </div>
  );
}
