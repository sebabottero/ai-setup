# What this setup covers and what is missing

> This file is bilingual: English first, Spanish below (`## Español`).

## ✅ Solved by this folder
| Gap | Solution |
|---|---|
| No role-based agents | 6 agents: `flow-ticket`, `sub-review`, `sub-builder`, `sub-tester`, `leaf-verify`, `meta-setup` |
| Orchestration by hand, stage by stage | `ticket-flow` skill + `flow-ticket` agent: one writer in its worktree, reads in parallel, 2 gates |
| Same model for everything | Tiers per agent (`tier`), mapped per tool |
| No secret protection | `deny_files` and `deny_home_dirs` in `policy.json`; the hook also blocks them through the shell |
| Destructive git commands unrestricted | `ask_commands`: reset --hard, clean, rebase, restore, checkout --, branch -D, stash drop, merge, push --force, rm -rf |
| Too many prompts for harmless commands | `allow_commands` / `allow_mcp_tools`: reads run without OK; `ask` and `deny` still win over `allow` |
| Stale rules after editing the policy | The installer removes rules it generated earlier and no layer produces any more; hand-added ones stay |
| Handoff prompts written by hand | `session-handoff` skill |
| "Run the checks" every time | `validate` skill + `leaf-verify` agent |
| PR-vs-ticket review by hand | `pr-review-ticket` skill |
| Everything tied to one tool | Neutral `core/` + `adapters/<tool>/` |
| Private rules mixed with the shared ones | Layers: any folder with the shape of `core/`, in this repo or in another one (`--layers-dir`) |

## 🟡 Missing (way of working, config cannot fix it)
- **Only one session writes per branch.** Decide it when opening each workspace.
- **"Out of scope" written down at the start** of every task.
- **Concrete acceptance criteria** before executing.
- **Final receipt** on every task (it is in `core/AGENTS.md`: demand it).
- **Use plan mode / a plan agent** on ambiguous tasks.
- **Bypass mode:** with `policy.json` it is safer, but whatever is not listed is still allowed.

## ⚪ Optional, later
- A tool to cut long command output.
- A second model family as reviewer (OpenCode with another provider + the `sub-review` agent).
- `srt` as an OS-level wall for OpenCode; `ask_mcp_tools` translated for OpenCode.

## 🧱 Design decisions
| Decision | Why |
|---|---|
| Shared `core/guard/guard.py`: hook in Claude, plugin in OpenCode, tests (with known gaps) | One logic for both tools; OpenCode only had globs. Includes git's global options (`--no-pager`, `-c`, `--git-dir`) |
| Claude's native sandbox from `policy.json` + `auto` mode | A regex is never complete: the wall has to be the operating system |
| `protected_paths`: editing policy, guard, hooks, plugins, installer or tests asks for OK | An agent that edits its own rules has loose limits |
| `AGENTS.md` kept short; `sub-review` audits tests and minimal diff | Fewer always-loaded instructions = better compliance; avoid duplicate paths and tailor-made tests |
| `ticket-flow` with a single writer | Parallel writers clash; fewer parts that can fail |
| `adapters/<tool>/` accepts its own skills, agents, hooks and plugins | Tune each tool without breaking the common contract |
| Layers only add, never remove a rule | A private layer can tighten the policy but never loosen the shared one |
| `core` always comes from this repo; `--layers-dir` cannot shadow it | An external folder cannot replace the rules that guard everything else |
| A layer outside the repo is protected like one inside | Its `policy.json` can add `allow` rules: editing it asks for OK |
| The installer checks the composed policy before writing | The tests of this repo cannot see your private layers |
| Third-party skills are not bundled | Their license and updates stay with their authors: `./add-skill.sh <url>` |

---

## Español

## ✅ Resuelto por esta carpeta
| Hueco | Solución |
|---|---|
| Sin agentes por rol | 6 agentes: `flow-ticket`, `sub-review`, `sub-builder`, `sub-tester`, `leaf-verify`, `meta-setup` |
| Orquestación a mano, etapa por etapa | Skill `ticket-flow` + agente `flow-ticket`: un solo escritor en su worktree, lecturas en paralelo, 2 puertas |
| El mismo modelo para todo | Niveles por agente (`tier`), traducidos a cada herramienta |
| Sin protección de secretos | `deny_files` y `deny_home_dirs` en `policy.json`; el hook también los bloquea por la shell |
| Comandos destructivos de git sin restricción | `ask_commands`: reset --hard, clean, rebase, restore, checkout --, branch -D, stash drop, merge, push --force, rm -rf |
| Demasiados avisos para comandos inofensivos | `allow_commands` / `allow_mcp_tools`: las lecturas corren sin OK; `ask` y `deny` siguen ganando a `allow` |
| Reglas viejas tras editar la policy | El instalador quita las reglas que generó antes y que ninguna capa produce ya; las añadidas a mano se quedan |
| Prompts de traspaso escritos a mano | Skill `session-handoff` |
| "Pasa los checks" cada vez | Skill `validate` + agente `leaf-verify` |
| Revisión de PR contra ticket a mano | Skill `pr-review-ticket` |
| Todo atado a una herramienta | `core/` neutro + `adapters/<herramienta>/` |
| Reglas privadas mezcladas con las compartidas | Capas: cualquier carpeta con la forma de `core/`, en este repo o en otro (`--layers-dir`) |

## 🟡 Falta (forma de trabajar, la configuración no lo arregla)
- **Solo una sesión escribe por rama.** Decídelo al abrir cada workspace.
- **"Fuera de alcance" escrito al inicio** de cada tarea.
- **Criterios de aceptación concretos** antes de ejecutar.
- **Recibo final** en cada tarea (está en `core/AGENTS.md`: exígelo).
- **Usar modo plan o un agente de plan** en tareas ambiguas.
- **Modo bypass:** con `policy.json` es más seguro, pero lo que no está listado sigue permitido.

## ⚪ Opcional, más adelante
- Una herramienta que recorte la salida larga de los comandos.
- Una segunda familia de modelos como revisora (OpenCode con otro proveedor + el agente `sub-review`).
- `srt` como muro a nivel de sistema operativo para OpenCode; `ask_mcp_tools` traducido para OpenCode.

## 🧱 Decisiones de diseño
| Decisión | Por qué |
|---|---|
| `core/guard/guard.py` compartido: hook en Claude, plugin en OpenCode, tests (con huecos conocidos) | Una sola lógica para ambas herramientas; OpenCode solo tenía globs. Incluye las opciones globales de git (`--no-pager`, `-c`, `--git-dir`) |
| Sandbox nativo de Claude desde `policy.json` + modo `auto` | Una regex nunca es completa: el muro tiene que ser el sistema operativo |
| `protected_paths`: editar policy, guard, hooks, plugins, instalador o tests pide OK | Un agente que edita sus propias reglas tiene límites flojos |
| `AGENTS.md` corto; `sub-review` audita tests y diff mínimo | Menos instrucciones siempre cargadas = mejor cumplimiento; evita caminos duplicados y tests a medida |
| `ticket-flow` con un solo escritor | Los escritores en paralelo chocan; menos piezas que pueden fallar |
| `adapters/<herramienta>/` acepta sus propias skills, agentes, hooks y plugins | Ajusta cada herramienta sin romper el contrato común |
| Las capas solo suman, nunca quitan una regla | Una capa privada puede endurecer la policy pero nunca aflojar la compartida |
| `core` siempre sale de este repo; `--layers-dir` no puede taparlo | Una carpeta externa no puede sustituir las reglas que protegen todo lo demás |
| Una capa fuera del repo se protege igual que una de dentro | Su `policy.json` puede añadir reglas `allow`: editarla pide OK |
| El instalador revisa la política compuesta antes de escribir | Los tests de este repo no ven tus capas privadas |
| Las skills de terceros no se incluyen | Su licencia y sus actualizaciones se quedan con sus autores: `./add-skill.sh <url>` |
