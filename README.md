# AI usage and details added for Phase 4

## AI classification (Phase 4)

The organizer can optionally call a third-party LLM to classify file names when rules fail. Key points:

- Supported services: OpenAI and Anthropic (SDKs must be installed and API keys set in environment variables).
- Only filenames are sent to the model (no file content). Enable AI explicitly in config or via CLI.
- The script enforces strict JSON-only outputs from the model and validates categories against the configured list.
- Raw AI responses are not saved by default; enable `AI.保存原始响应` in config to store raw responses for debugging.

CLI example to enable AI for a run (assuming config flags set):

  python3 media_organizer.py --root /path/to/media --dry-run --preview --verbose

To explicitly set AI flags via CLI (overrides config):
  --ai-enable
  --ai-service openai|anthropic
  --ai-model <model-name>
  --ai-batch <n>
  --ai-save-raw

See full README for details.
