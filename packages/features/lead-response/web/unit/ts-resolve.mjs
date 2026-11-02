// Lets `node --test` load the app's TypeScript, which imports its siblings without a file extension.
import { register } from "node:module";

register("./ts-resolve-hooks.mjs", import.meta.url);
