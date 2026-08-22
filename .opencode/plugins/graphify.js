// graphify OpenCode plugin
// Injects a graph-first reminder before the first bash tool call when the graph exists.
import { existsSync } from "fs";
import { join } from "path";

export const GraphifyPlugin = async ({ directory }) => {
  let reminded = false;
  const graphPath = join(directory, "graphify-out", "graph.json");
  const pythonPath = join(directory, "graphify-out", ".graphify_python");

  return {
    "tool.execute.before": async (input, output) => {
      if (reminded) return;
      if (!existsSync(graphPath)) return;

      if (input.tool === "bash") {
        const queryHint = existsSync(pythonPath)
          ? "Use graphify-out/.graphify_python with -m graphify query."
          : "Resolve the Graphify interpreter using the graphify skill before querying.";
        output.args.command =
          `printf '%s\\n' '[graphify] graphify-out/graph.json PRESENT. It is intentionally gitignored local state, not missing. ${queryHint} Do not read or grep repository source before the graph query.' && ` +
          output.args.command;
        reminded = true;
      }
    },
  };
};
