import TaskWorkspace from "@/components/TaskWorkspace";
export default async function TaskPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ demo?: string }>;
}) {
  const { id } = await params;
  const { demo } = await searchParams;
  return <TaskWorkspace key={id} id={id} demoMode={demo === "1"} />;
}
