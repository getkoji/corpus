/**
 * [accuracy-40] Honest per-category accuracy over the corpus.
 *
 * Runs the production extract engine (this checkout, with the oss-471 fix) over
 * every category and writes fieldbench-format predictions per doc. A separate
 * Python step scores them with the canonical fieldbench scorer. Nothing here is
 * corpus-specific — it reads <corpus>/<cat>/{documents,expected,schemas}.
 */
import { readFileSync, readdirSync, existsSync, writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { parse as parseYaml } from "yaml";
import { OpenAIProvider } from "./providers";
import { intelligentExtract } from "./intelligent-pipeline";

const corpus = process.argv[2];
const outRoot = process.argv[3];
const perCat = Number(process.env.LIMIT ?? "0"); // 0 = all
const conc = Number(process.env.CONC ?? "4");
const model = "gpt-4o-mini";

const categories = readdirSync(corpus, { withFileTypes: true })
  .filter(
    (d) =>
      d.isDirectory() &&
      existsSync(join(corpus, d.name, "documents")) &&
      existsSync(join(corpus, d.name, "expected")) &&
      existsSync(join(corpus, d.name, "schemas")),
  )
  .map((d) => d.name)
  .sort();

const provider = new OpenAIProvider(model, process.env.OPENAI_API_KEY);

async function pool<T>(items: T[], n: number, fn: (t: T) => Promise<void>) {
  const q = [...items];
  await Promise.all(
    Array.from({ length: Math.min(n, q.length) }, async () => {
      while (q.length) await fn(q.shift()!);
    }),
  );
}

const summary: Record<string, number> = {};
// Schema per document: prefer the manifest-declared schema (a category can mix
// document types — e.g. irs_forms holds both W-2 and 1099-NEC, each with its own
// schema and its own expected fields). Fall back to the sole category schema.
const schemaCache = new Map<string, Record<string, unknown>>();
function loadSchema(path: string): Record<string, unknown> {
  let s = schemaCache.get(path);
  if (!s) {
    s = parseYaml(readFileSync(path, "utf-8"));
    schemaCache.set(path, s);
  }
  return s;
}

for (const cat of categories) {
  const docsDir = join(corpus, cat, "documents");
  const expDir = join(corpus, cat, "expected");
  const schDir = join(corpus, cat, "schemas");
  const manDir = join(corpus, cat, "manifests");
  const defaultSchema = readdirSync(schDir).find((f) => f.endsWith(".yaml"));
  if (!defaultSchema) continue;

  let docs = readdirSync(docsDir)
    .filter((f) => f.endsWith(".md"))
    .filter((f) => existsSync(join(expDir, f.replace(".md", ".expected.json"))))
    .sort();
  if (perCat > 0) docs = docs.slice(0, perCat);

  const outDir = join(outRoot, cat);
  mkdirSync(outDir, { recursive: true });
  let done = 0;
  const t0 = Date.now();
  await pool(docs, conc, async (docFile) => {
    const stem = docFile.replace(".md", "");
    const md = readFileSync(join(docsDir, docFile), "utf-8");
    // Resolve this doc's schema from its manifest; the `schema` field is a
    // corpus-root-relative path (e.g. "irs_forms/schemas/form_w2.yaml").
    let schemaPath = join(schDir, defaultSchema);
    const manPath = join(manDir, `${stem}.json`);
    if (existsSync(manPath)) {
      const declared = JSON.parse(readFileSync(manPath, "utf-8")).schema as string | undefined;
      if (declared) schemaPath = join(corpus, declared);
    }
    try {
      const r = await intelligentExtract(md, loadSchema(schemaPath), provider, model);
      writeFileSync(join(outDir, `${stem}.json`), JSON.stringify(r.extracted ?? {}));
    } catch (e) {
      // Write all-null rather than skip, so a failed doc scores as a miss.
      writeFileSync(join(outDir, `${stem}.json`), "{}");
      console.error(`  FAIL ${cat}/${stem}: ${(e as Error).message?.slice(0, 120)}`);
    }
    done++;
  });
  summary[cat] = docs.length;
  console.log(`${cat}: ${docs.length} docs in ${((Date.now() - t0) / 1000).toFixed(0)}s`);
}

writeFileSync(
  join(outRoot, "_run.json"),
  JSON.stringify({ model, corpus, categories: summary, generated: process.env.RUN_DATE }, null, 2),
);
console.log(`\ndone -> ${outRoot}`);
