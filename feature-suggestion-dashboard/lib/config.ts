import { z } from "zod";
export const configSchema = z
  .object({
    modules: z
      .array(
        z.object({
          id: z.string().regex(/^[a-z0-9-]{1,40}$/),
          name: z.string().trim().min(1).max(60),
          keywords: z.array(z.string().trim().min(1).max(60)).max(30),
          destination: z.string().regex(/^$|^[CGDU][A-Z0-9]{7,}$/),
        }),
      )
      .min(1)
      .max(20),
  })
  .refine(
    (c) => new Set(c.modules.map((m) => m.id)).size === c.modules.length,
    "Module IDs must be unique",
  );
export const defaultConfig = {
  modules: [
    {
      id: "feed",
      name: "Feed & social",
      keywords: ["feed", "post", "comment", "follow", "friend"],
      destination: "",
    },
    {
      id: "gameplay",
      name: "Gameplay & leagues",
      keywords: ["duel", "league", "puzzle", "game", "match"],
      destination: "",
    },
    {
      id: "learning",
      name: "Learning",
      keywords: ["learn", "lesson", "video", "practice"],
      destination: "",
    },
    {
      id: "profile",
      name: "Profile & rewards",
      keywords: ["profile", "streak", "reward", "merch", "coin"],
      destination: "",
    },
    { id: "other", name: "Other suggestions", keywords: [], destination: "" },
  ],
};
