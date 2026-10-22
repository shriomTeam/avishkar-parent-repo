import { AuthenticatedWorkspace } from "../components/authenticated-workspace";
import { requireAuth } from "@clinic/core/web/auth/server";
import { requireFeature } from "@clinic/core/web/api";

export default async function VoiceLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  await requireFeature("voice_receptionist");
  const auth = await requireAuth();
  return (
    <div
      data-testid="voice-app"
      className="bg-canvas font-brand text-[15px] leading-normal text-ink app:[zoom:0.9]"
    >
      <AuthenticatedWorkspace
        key={`${auth.user.id}:${auth.workspace?.id}`}
        initial={auth}
      >
        {children}
      </AuthenticatedWorkspace>
    </div>
  );
}
