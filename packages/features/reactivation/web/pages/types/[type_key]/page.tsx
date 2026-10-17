import Link from "next/link";
import { Card, PageHeader } from "@clinic/ui";

import { EmptyState } from "../../../components/kit";

export default function TypePage() {
  return (
    <>
      <Link href="/reactivation" className="dp-back">
        ← Back to overview
      </Link>
      <PageHeader title="Patients of this type" />
      <Card>
        <EmptyState title="The patient list is coming soon">
          You&apos;ll see each patient, why they matched, and how likely they
          are to come back.
        </EmptyState>
      </Card>
    </>
  );
}
