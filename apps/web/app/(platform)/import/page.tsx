import { requireManagement } from "@/lib/api";
import { PageHeader } from "@clinic/ui";

import { ImportWizard } from "./import-wizard";

export default async function ImportPage() {
  await requireManagement();
  return (
    <>
      <PageHeader
        title="Import clinic data"
        description="Upload an export from any EMR, POS or spreadsheet. Import patients first, then appointments, then transactions. We suggest how its columns map; you confirm. The mapping is saved, so the next export from the same system imports as-is."
      />
      <ImportWizard />
    </>
  );
}
