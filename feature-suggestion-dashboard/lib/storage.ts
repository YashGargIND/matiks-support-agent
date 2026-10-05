import {
  mkdir,
  readFile,
  writeFile,
  rename,
  open,
  unlink,
} from "node:fs/promises";
import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { configSchema, defaultConfig } from "./config";
import type { Config, Run } from "./types";
const root = () => process.env.FEATURE_DATA_DIR || join(process.cwd(), "data");
const lockState = globalThis as typeof globalThis & {
  featureLockRuntime?: string;
};
lockState.featureLockRuntime ??= randomUUID();
export async function saveJson(name: string, data: unknown) {
  await mkdir(root(), { recursive: true, mode: 0o700 });
  const path = join(root(), name);
  const temp = `${path}.${randomUUID()}.tmp`;
  await writeFile(temp, JSON.stringify(data, null, 2), { mode: 0o600 });
  await rename(temp, path);
}
export async function readJson<T>(name: string): Promise<T> {
  return JSON.parse(await readFile(join(root(), name), "utf8"));
}
export async function getConfig(): Promise<Config> {
  try {
    return configSchema.parse(
      JSON.parse(await readFile(join(root(), "config.json"), "utf8")),
    );
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") return defaultConfig;
    throw new Error("Saved module configuration is invalid.");
  }
}
export const saveConfig = (data: unknown) =>
  saveJson("config.json", configSchema.parse(data));
export const saveRun = (run: Run) => saveJson(`run-${run.id}.json`, run);
export async function getRun(id: string): Promise<Run> {
  if (!/^[a-f0-9]{64}$/.test(id)) throw new Error("Invalid summary ID.");
  return JSON.parse(await readFile(join(root(), `run-${id}.json`), "utf8"));
}
export async function withRunLock<T>(
  id: string,
  work: () => Promise<T>,
): Promise<T> {
  if (!/^[a-f0-9]{64}$/.test(id)) throw new Error("Invalid summary ID.");
  await mkdir(root(), { recursive: true, mode: 0o700 });
  const path = join(root(), `${id}.lock`);
  let lock;
  try {
    lock = await open(path, "wx", 0o600);
    await lock.writeFile(
      JSON.stringify({
        pid: process.pid,
        runtime: lockState.featureLockRuntime,
      }),
    );
  } catch {
    try {
      const owner = JSON.parse(await readFile(path, "utf8")) as { pid: number };
      if (!Number.isInteger(owner.pid) || owner.pid < 1)
        throw new Error("Invalid lock owner.");
      try {
        process.kill(owner.pid, 0);
      } catch (e) {
        if ((e as NodeJS.ErrnoException).code === "ESRCH") {
          await unlink(path);
          return withRunLock(id, work);
        }
        throw e;
      }
    } catch {
      /* A live or unidentified lock must not be removed. */
    }
    throw new Error(
      "This summary is already being processed. Try again when it finishes.",
    );
  }
  try {
    return await work();
  } finally {
    await lock.close();
    await unlink(path);
  }
}
