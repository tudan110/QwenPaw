import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_CONVERSATION_PROCESS_RECORD_DISPLAY_MODE,
  DEFAULT_CONVERSATION_PROCESS_RECORD_DETAILS_EXPANDABLE,
  CONVERSATION_PROCESS_RECORD_DETAILS_EXPANDABLE_CHANGED_EVENT,
  CONVERSATION_PROCESS_RECORD_DISPLAY_MODE_CHANGED_EVENT,
  normalizeConversationProcessRecordDetailsExpandable,
  normalizeConversationProcessRecordDisplayMode,
  readConversationProcessRecordDetailsExpandable,
  readConversationProcessRecordDisplayMode,
  writeConversationProcessRecordDetailsExpandable,
  writeConversationProcessRecordDisplayMode,
} from "./conversationSettings.ts";

test("process-record display mode keeps collapsed as its safe default", () => {
  assert.equal(DEFAULT_CONVERSATION_PROCESS_RECORD_DISPLAY_MODE, "collapsed");
  assert.equal(normalizeConversationProcessRecordDisplayMode("expanded"), "expanded");
  assert.equal(normalizeConversationProcessRecordDisplayMode("collapsed"), "collapsed");
  assert.equal(normalizeConversationProcessRecordDisplayMode("unexpected"), "collapsed");
  assert.equal(readConversationProcessRecordDisplayMode(), "collapsed");
  assert.equal(writeConversationProcessRecordDisplayMode("expanded"), "expanded");
});

test("process-record details are expandable by default", () => {
  assert.equal(DEFAULT_CONVERSATION_PROCESS_RECORD_DETAILS_EXPANDABLE, true);
  assert.equal(normalizeConversationProcessRecordDetailsExpandable(null), true);
  assert.equal(normalizeConversationProcessRecordDetailsExpandable("unexpected"), true);
});

test("process-record detail preference accepts persisted boolean strings", () => {
  assert.equal(normalizeConversationProcessRecordDetailsExpandable("true"), true);
  assert.equal(normalizeConversationProcessRecordDetailsExpandable("false"), false);
  assert.equal(normalizeConversationProcessRecordDetailsExpandable(true), true);
  assert.equal(normalizeConversationProcessRecordDetailsExpandable(false), false);
});

test("process-record detail preference persists and publishes changes", () => {
  const stored = new Map<string, string>();
  const events: Array<{ type: string; detail: unknown }> = [];
  const originalWindow = globalThis.window;
  const originalCustomEvent = globalThis.CustomEvent;

  class FakeCustomEvent {
    type: string;
    detail: unknown;

    constructor(type: string, init?: { detail?: unknown }) {
      this.type = type;
      this.detail = init?.detail;
    }
  }

  Object.assign(globalThis, {
    CustomEvent: FakeCustomEvent,
    window: {
      localStorage: {
        getItem: (key: string) => stored.get(key) ?? null,
        setItem: (key: string, value: string) => stored.set(key, value),
      },
      dispatchEvent: (event: { type: string; detail: unknown }) => {
        events.push(event);
        return true;
      },
    },
  });

  try {
    assert.equal(writeConversationProcessRecordDetailsExpandable(false), false);
    assert.equal(readConversationProcessRecordDetailsExpandable(), false);
    assert.equal(events.length, 1);
    assert.equal(
      events[0]?.type,
      CONVERSATION_PROCESS_RECORD_DETAILS_EXPANDABLE_CHANGED_EVENT,
    );
    assert.deepEqual(events[0]?.detail, { expandable: false });
  } finally {
    Object.assign(globalThis, {
      CustomEvent: originalCustomEvent,
      window: originalWindow,
    });
  }
});

test("process-record display mode persists and publishes changes", () => {
  const stored = new Map<string, string>();
  const events: Array<{ type: string; detail: unknown }> = [];
  const originalWindow = globalThis.window;
  const originalCustomEvent = globalThis.CustomEvent;

  class FakeCustomEvent {
    type: string;
    detail: unknown;

    constructor(type: string, init?: { detail?: unknown }) {
      this.type = type;
      this.detail = init?.detail;
    }
  }

  Object.assign(globalThis, {
    CustomEvent: FakeCustomEvent,
    window: {
      localStorage: {
        getItem: (key: string) => stored.get(key) ?? null,
        setItem: (key: string, value: string) => stored.set(key, value),
      },
      dispatchEvent: (event: { type: string; detail: unknown }) => {
        events.push(event);
        return true;
      },
    },
  });

  try {
    assert.equal(writeConversationProcessRecordDisplayMode("expanded"), "expanded");
    assert.equal(readConversationProcessRecordDisplayMode(), "expanded");
    assert.equal(events.length, 1);
    assert.equal(
      events[0]?.type,
      CONVERSATION_PROCESS_RECORD_DISPLAY_MODE_CHANGED_EVENT,
    );
    assert.deepEqual(events[0]?.detail, { mode: "expanded" });
  } finally {
    Object.assign(globalThis, {
      CustomEvent: originalCustomEvent,
      window: originalWindow,
    });
  }
});
