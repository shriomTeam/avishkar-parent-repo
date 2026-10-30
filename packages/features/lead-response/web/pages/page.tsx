import { redirect } from "next/navigation";

import { SETTINGS_PATH } from "../lib/paths";

/** Settings is the only section today; the task list becomes this page with the staff dashboard. */
export default function LeadResponseHome() {
  redirect(SETTINGS_PATH);
}
