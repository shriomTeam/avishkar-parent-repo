import "@/styles/voice.css";
export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <div className="voice-scope">{children}</div>;
}
