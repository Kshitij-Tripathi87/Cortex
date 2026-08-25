import type { Role } from "../roles";
import { ROLES } from "../roles";

interface RoleSwitcherProps {
  current: Role;
  onChange: (r: Role) => void;
}

export function RoleSwitcher({ current, onChange }: RoleSwitcherProps) {
  return (
    <div className="flex flex-wrap gap-2 rounded-xl border border-slate-200 bg-white p-2 shadow-sm">
      {ROLES.map((role) => {
        const active = role.id === current;
        return (
          <button
            key={role.id}
            type="button"
            onClick={() => onChange(role.id)}
            className={`rounded-lg px-4 py-2 text-sm font-semibold transition-colors ${
              active ? "bg-indigo-600 text-white shadow" : "text-slate-600 hover:bg-slate-100"
            }`}
            title={role.subtitle}
          >
            {role.label}
         </button>
        );
      })}
    </div>
  );
}
