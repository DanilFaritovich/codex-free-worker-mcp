# OpenCode final result protocol

The adapter targets the `opencode run --format json` event protocol verified against
OpenCode 1.18.30. It does not infer completion from arbitrary text or look for JSON braces.

Source evidence:

- [`cli/cmd/run.ts`](https://github.com/anomalyco/opencode/blob/v1.18.30/packages/opencode/src/cli/cmd/run.ts#L643-L752)
  wraps emitted events with `sessionID`; parts carry `sessionID` and `messageID`.
  It emits `step_start`, completed `text` (`part.time.end`), `tool_use` and `step_finish`.
  It filters parts to the current session. Assistant `message.updated` metadata and the
  session idle event are **not** emitted in JSON mode.
- [`session/processor.ts`](https://github.com/anomalyco/opencode/blob/v1.18.30/packages/opencode/src/session/processor.ts#L397-L515)
  creates step/text parts for its assistant message and records the model's finish reason
  in the `step-finish` part. Thus a matching `step_finish` with reason `stop` provides the
  completion signal available in CLI stdout; `tool-calls`, `length` and unknown reasons
  cannot certify a final answer.
- A read-only, ID-scoped inspection of session `ses_e5794c3b8ffeST54p2l69X2Ebg`, final
  assistant message `msg_1a86d5dc90010LJilGBfe4WCRJ`, confirmed `role=assistant`,
  `finish=stop`, a completed text part, and a `step-finish` part with `reason=stop`.
  The persisted text also contains literal escaped quotes around JSON keys. Removing the
  old marker requirement alone does not make that particular text valid JSON; it needs
  syntax repair. Tests use constructed protocol events and do not access the database.

The collector retains at most `max_result_chars + 1` characters for the active step.
It correlates the start, text and finish by session/message IDs, concatenates the completed
non-synthetic text parts, and validates the entire final text. A later unfinished step
invalidates an earlier candidate; multiple terminal answers are ambiguous and rejected.
Tool results and synthetic parts are never parsed as reports. A step containing a tool
call cannot itself supply a terminal report. Process/session errors override valid text.
Unknown or incomplete protocol versions fail closed rather than accepting the last text.

The primary prompt and the isolated repair prompt both require one plain JSON object.
Legacy markers are deliberately unsupported: searching inside wrappers or surrounding
prose would weaken the whole-answer contract. Such text is invalid; a repair attempt cannot
pass the existing fact-preservation check unless the original starts with a readable object.
Syntax/field-shape repair remains limited to one isolated request without tools, task text
or session history, within the shared timeout and the 60-second repair cap. Missing,
ambiguous, oversized and process-failed results do not trigger repair. Existing top-level
fact checks are preserved; they cannot prove the truth of claims or recover facts that
cannot be decoded before a syntax error. No live model run is needed for protocol tests.
