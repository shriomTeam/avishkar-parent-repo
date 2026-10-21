import { requireFeature } from "@clinic/core/web/api";

import { ImportPage, ImportRefused } from "../../components/import-page";
import { canRunRole } from "../../lib/roles";

export default async function ImportRoute() {
  // The role is read on the server too, so a role that cannot import never gets the importer, even by URL.
  const me = await requireFeature("reactivation");
  return canRunRole(me.role) ? <ImportPage /> : <ImportRefused />;
}
