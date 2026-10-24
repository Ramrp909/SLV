## 18. AI-Assisted Build Plan (pointer)

The project is built with AI coding assistants inside VS Code (OpenRouter free models through the Kilo extension). The full task-by-task plan is in the separate file **`ai-build-task-planner.md`**; the rules file **`AGENTS.md`** is placed in the project root so every task starts with the same non-negotiable rules.

Summary of the method:
1. **One small task at a time:** task, AI generates code, build and run, test, review, commit, then the next task.
2. **Backend and database first, frontend last.** The frontend is built only after the API is complete and documented (OpenAPI), then styled from design mockups (Figma AI or Claude Design) in a final design pass.
3. **Pure functions and tests first** for money, GST, stock and commission logic. The task planner marks these as **critical tasks** that need a second review and, where possible, a stronger model.
4. **Context packs:** each task attaches only the blueprint sections it needs (the blueprint is also supplied split by section) so small context windows and free-tier request limits are enough.
5. **Never share real customer or business data** with free endpoints; use sample data only.
