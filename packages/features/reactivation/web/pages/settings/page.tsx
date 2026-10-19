import { Card, EmptyState, PageHead } from "../../components/kit";

export default function SettingsPage() {
  return (
    <>
      <PageHead
        title="Settings"
        description="How patients are judged dormant and when the analysis runs."
      />
      <Card>
        <EmptyState title="Settings are coming soon">
          You&apos;ll be able to change the rules, return-rate assumptions and
          schedule here.
        </EmptyState>
      </Card>
    </>
  );
}
