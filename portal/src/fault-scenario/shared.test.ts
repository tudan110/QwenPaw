import assert from 'node:assert/strict';
import test from 'node:test';

import {
  getFaultScenarioDrawerClassName,
  getFaultScenarioResult,
  getFaultScenarioSummary,
} from './shared';

test('adds dark theme class for fault scenario drawer portals', () => {
  assert.equal(getFaultScenarioDrawerClassName('dark'), 'fault-scenario-log-drawer theme-dark');
  assert.equal(getFaultScenarioDrawerClassName('light'), 'fault-scenario-log-drawer');
});

test('uses shared diagnosis response helpers for result summaries', () => {
  const response = { result: { summary: '已完成关联分析。' } };

  assert.deepEqual(getFaultScenarioResult(response), response.result);
  assert.equal(getFaultScenarioSummary(getFaultScenarioResult(response)), '已完成关联分析。');
  assert.equal(getFaultScenarioSummary(getFaultScenarioResult({})), '已完成关联分析。');
});
