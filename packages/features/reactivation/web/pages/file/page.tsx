import { requireFeature } from "@clinic/core/web/api";

import { FileRefused, FileViewer } from "../../components/file-viewer";
import { canRunRole } from "../../lib/roles";

export default async function FileRoute() {
  // The role is read on the server too: only a role that can import ever has a file, so others never get the viewer.
  const me = await requireFeature("reactivation");
  return canRunRole(me.role) ? <FileViewer /> : <FileRefused />;
}
