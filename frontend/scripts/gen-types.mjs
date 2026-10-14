// Generates src/generated/*.ts from the JSON Schemas in ../schema, which the backend's pydantic
// models write (`uv run python -m optopus_studio.schema`). Never edit the generated files.
import { readdir, readFile, writeFile } from "node:fs/promises";
import { compile } from "json-schema-to-typescript";

const schemaDir = new URL("../../schema/", import.meta.url);
const outDir = new URL("../src/generated/", import.meta.url);

for (const file of (await readdir(schemaDir)).filter((f) => f.endsWith(".json")).sort()) {
  const schema = JSON.parse(await readFile(new URL(file, schemaDir), "utf8"));
  const ts = await compile(schema, schema.title, {
    bannerComment: `// Generated from schema/${file} by \`npm run gen:types\`. Do not edit.`,
    additionalProperties: false,
    unreachableDefinitions: false,
    style: { printWidth: 100 },
  });
  await writeFile(new URL(file.replace(/\.json$/, ".ts"), outDir), ts);
  console.log(`wrote src/generated/${file.replace(/\.json$/, ".ts")}`);
}
