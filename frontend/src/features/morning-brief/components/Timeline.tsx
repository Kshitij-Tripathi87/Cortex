import type { DecisionBrief } from "../api/client";

interface TimelineProps {
  brief: DecisionBrief;
}

export function Timeline({ brief }: TimelineProps) {
  return (
    <section className="rounded-2xl border bg-white p-6 shadow-sm">
      <header className="mb-4">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">Timeline</h3>
        <p className="mt-1 text-xs text-slate-500">Inventory depletion at fixed checkpoints</p>
     </header>
      <ol className="space-y-3">
        {brief.timeline.events.map((event, i) => {
          const tone =
            event.status === "stocked_out"
              ? "border-red-300 bg-red-50"
              : event.status === "at_safety"
                ? "border-amber-300 bg-amber-50"
                : event.status === "below_safety"
                  ? "border-orange-300 bg-orange-50"
                  : "border-slate-200 bg-slate-50";
          return (
            <li key={i} className={`flex gap-4 rounded-xl border p-4 ${tone}`}>
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-slate-900 font-bold tabular-nums text-white">
                {event.hour}h
             </div>
              <div className="flex-1">
                <p className="text-sm font-bold">{event.title}</p>
                <p className="mt-0.5 text-xs text-slate-600">{event.description}</p>
             </div>
              <span className="self-start rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider">
                {event.status.replace("_", " ")}
             </span>
           </li>
          );
        })}
     </ol>
   </section>
  );
}
