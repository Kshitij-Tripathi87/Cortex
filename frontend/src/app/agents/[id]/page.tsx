import AgentDetailClient from "./agent-detail-client";

interface AgentDetailPageProps {
  params: Promise<{ id: string }>;
}

export default async function AgentDetailPage({ params }: AgentDetailPageProps) {
  const { id } = await params;
  return <AgentDetailClient agentId={id} />;
}
