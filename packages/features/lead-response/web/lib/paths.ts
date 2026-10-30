/** Where the pages live. No "use client" here: server files (the layout and the home page) import these values too, and a
 *  value imported from a client file arrives on the server as a reference, not as the string. */
export const ROOT = "/lead-response";
export const SETTINGS_PATH = `${ROOT}/settings`;
