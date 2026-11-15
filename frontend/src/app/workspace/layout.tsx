import { redirect } from "next/navigation";

/**
 * The pre-RC0 workspace shell rendered seeded operational fixtures. Keep old
 * links safe and discoverable by routing them to the authenticated canonical
 * cockpit instead of allowing a legacy page to present fabricated state.
 */
export default function LegacyWorkspaceLayout() {
  redirect("/nexus/cockpit");
}
