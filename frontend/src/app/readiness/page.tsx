import { redirect } from "next/navigation";

export default function LegacyReadinessPage() {
  redirect("/upload");
}
