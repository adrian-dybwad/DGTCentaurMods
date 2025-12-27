/**
 * game_client.js - Single SSE client for receiving game state updates.
 *
 * This prevents multiple paths (SSE + polling + per-page handlers) from fighting.
 *
 * Public API:
 *   window.gameClient.start({ boardId: 'board1', pgnTextareaId: 'lastpgn' })
 *   window.gameClient.stop()
 *
 * Emits:
 *   window.dispatchEvent(new CustomEvent('gameStateUpdate', { detail: state }))
 */

(function() {
  'use strict';

  let es = null;
  let lastFen = null;
  let config = { boardId: 'board1', pgnTextareaId: null };

  function setStatus(kind) {
    const el = document.getElementById('connection-status');
    if (!el) return;
    if (kind === 'connected') {
      el.className = 'tag is-success';
      el.innerHTML = '<span class="status-dot connected"></span> Connected';
      return;
    }
    if (kind === 'reconnecting') {
      el.className = 'tag is-warning';
      el.innerHTML = '<span class="status-dot pending"></span> Reconnecting';
      return;
    }
    el.className = 'tag is-danger';
    el.innerHTML = '<span class="status-dot disconnected"></span> Offline';
  }

  function applyState(state) {
    if (!state) return;

    // Update board.
    if (state.fen) {
      const placement = typeof window.normalizePlacementFen === 'function'
        ? window.normalizePlacementFen(state.fen)
        : (state.fen || '').split(' ')[0];
      if (placement && placement !== lastFen) {
        lastFen = placement;
        if (typeof window.updateChessboardPosition === 'function') {
          window.updateChessboardPosition(config.boardId, placement);
        }
      }
    }

    // Update PGN textarea if configured.
    if (config.pgnTextareaId && state.pgn) {
      const ta = document.getElementById(config.pgnTextareaId);
      if (ta) ta.value = state.pgn;
    }

    // Notify listeners (analysis, current game info, etc).
    window.dispatchEvent(new CustomEvent('gameStateUpdate', { detail: state }));
  }

  function start(userConfig) {
    config = Object.assign({ boardId: 'board1', pgnTextareaId: null }, userConfig || {});
    if (es) return; // Singleton.

    if (typeof EventSource === 'undefined') {
      setStatus('offline');
      return;
    }

    setStatus('reconnecting');
    es = new EventSource('/events');
    es.onopen = () => setStatus('connected');
    es.onerror = () => setStatus('reconnecting');
    es.onmessage = (event) => {
      try {
        const state = JSON.parse(event.data);
        applyState(state);
      } catch (e) {
        console.error('Error parsing game state:', e);
      }
    };
  }

  function stop() {
    if (es) {
      try { es.close(); } catch (e) { /* no-op */ }
      es = null;
    }
  }

  window.gameClient = { start, stop };
})();


