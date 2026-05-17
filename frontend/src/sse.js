import { api } from './api.js';
import { emit, EVENTS } from './state.js';

const RECONNECT_DELAY_MS = 5000;

export function connectSSE(onChange) {
  let es;
  let closed = false;

  function open() {
    es = new EventSource(api.eventsUrl());

    es.onopen = () => emit(EVENTS.SSE_STATUS, 'connected');

    es.onmessage = (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }
      if (msg.type === 'ping') return;
      emit(EVENTS.SSE_STATUS, 'updating');
      onChange(msg);
      setTimeout(() => emit(EVENTS.SSE_STATUS, 'connected'), 1500);
    };

    es.onerror = () => {
      emit(EVENTS.SSE_STATUS, 'disconnected');
      es.close();
      if (!closed) setTimeout(open, RECONNECT_DELAY_MS);
    };
  }

  open();

  return () => {
    closed = true;
    es?.close();
  };
}
