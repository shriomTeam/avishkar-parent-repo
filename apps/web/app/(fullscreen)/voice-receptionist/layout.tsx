import "@/styles/voice.css";
import { AuthenticatedWorkspace } from "@/components/voice/authenticated-workspace";
import { requireAuth } from "@/lib/auth/server";
import { requireFeature } from "@/lib/api";

export default async function VoiceLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  await requireFeature("voice_receptionist");
  const auth = await requireAuth();
  return (
    <div className="voice-scope">
      <AuthenticatedWorkspace
        key={`${auth.user.id}:${auth.workspace?.id}`}
        initial={auth}
      >
        {children}
      </AuthenticatedWorkspace>
    </div>
  );
}
