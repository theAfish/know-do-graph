import { describe, expect, it, vi } from 'vitest';

import { connectSSE } from '../src/sse.js';
import { EVENTS, on } from '../src/state.js';

describe('SSE refresh wiring', () => {
  it('emits status updates and calls the refresh callback for graph events', () => {
    vi.useFakeTimers();
    const instances = [];
    class FakeEventSource {
      constructor(url) {
        this.url = url;
        instances.push(this);
      }

      close = vi.fn();
    }
    vi.stubGlobal('EventSource', FakeEventSource);
    const statuses = [];
    on(EVENTS.SSE_STATUS, (status) => statuses.push(status));
    const onChange = vi.fn();

    const stop = connectSSE(onChange);
    instances[0].onopen();
    instances[0].onmessage({ data: JSON.stringify({ type: 'graph_changed' }) });
    vi.advanceTimersByTime(1500);
    stop();

    expect(instances[0].url).toBe('/graph/events');
    expect(onChange).toHaveBeenCalledWith({ type: 'graph_changed' });
    expect(statuses).toEqual(['connected', 'updating', 'connected']);
    expect(instances[0].close).toHaveBeenCalled();
  });
});
