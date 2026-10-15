import { CallDetail } from "@/components/voice/calls";
export const metadata = { title: "Call details" };
export default async function Page({
  params,
}: {
  params: Promise<{ callId: string }>;
}) {
  const { callId } = await params;
  return <CallDetail id={callId} />;
}
