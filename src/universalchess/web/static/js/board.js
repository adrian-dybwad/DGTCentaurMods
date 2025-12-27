/**
 * board.js - Single source of truth for chessboard.js initialization and safe updates.
 *
 * Responsibilities:
 * - Initialize any `.chessboard-wrapper[data-board-id]` elements on the page
 * - Normalize full FEN to placement-only before passing to chessboard.js
 * - Provide a safe `updateChessboardPosition(boardId, fenLike)` that retries if the DOM isn't ready
 * - Assign stable square ids (`${boardId}-square-e4`) used by domarrow.js arrows
 */

(function() {
  'use strict';

  function normalizePlacementFen(fenLike) {
    return (fenLike || '').split(' ')[0];
  }

  function isChessboardDomReady(boardId) {
    const boardEl = document.getElementById(boardId);
    if (!boardEl) return false;
    return boardEl.querySelectorAll('div[class*="square-"]').length >= 64;
  }

  function assignSquareIds(boardId) {
    const boardEl = document.getElementById(boardId);
    if (!boardEl) return;
    const squares = boardEl.querySelectorAll('div[class*="square-"]');
    for (const el of squares) {
      const coordClass = Array.from(el.classList).find(c => /^square-[a-h][1-8]$/.test(c));
      if (!coordClass) continue;
      const coord = coordClass.substring('square-'.length);
      const desiredId = `${boardId}-square-${coord}`;
      if (el.id !== desiredId) {
        el.id = desiredId;
      }
    }
  }

  function ensureSquareIds(boardId, attemptsLeft) {
    assignSquareIds(boardId);
    const boardEl = document.getElementById(boardId);
    if (!boardEl) return;
    const assigned = boardEl.querySelectorAll(`div[id^="${boardId}-square-"]`).length;
    if (assigned >= 64) return;
    if (attemptsLeft <= 0) return;
    setTimeout(() => ensureSquareIds(boardId, attemptsLeft - 1), 50);
  }

  /**
   * Safely update a board position. Retries briefly if chessboard.js throws due to
   * DOM not ready or mid-render.
   */
  function updateChessboardPosition(boardId, fenLike, attempt) {
    const tries = typeof attempt === 'number' ? attempt : 0;
    const board = window[boardId];
    if (!board || typeof board.position !== 'function') return;

    const placement = normalizePlacementFen(fenLike);
    if (!placement) return;

    if (!isChessboardDomReady(boardId)) {
      if (tries < 20) {
        setTimeout(() => updateChessboardPosition(boardId, placement, tries + 1), 50);
      }
      return;
    }

    try {
      board.position(placement);
      ensureSquareIds(boardId, 10);
    } catch (e) {
      if (tries < 20) {
        setTimeout(() => updateChessboardPosition(boardId, placement, tries + 1), 50);
        return;
      }
      console.error('Failed to update board position:', e);
    }
  }

  function initOneBoard(wrapper) {
    const boardId = wrapper.getAttribute('data-board-id');
    if (!boardId) return;
    if (window[boardId]) return; // Already initialized.

    const fenRaw = wrapper.getAttribute('data-fen') || '';
    const placement = normalizePlacementFen(fenRaw) || 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR';
    const pieceTheme = wrapper.getAttribute('data-piece-theme');

    if (typeof window.Chessboard !== 'function') {
      console.error('Chessboard() not available. Ensure chessboardjs is loaded.');
      return;
    }

    const config = {
      position: placement,
      pieceTheme: pieceTheme || undefined,
    };

    window[boardId] = window.Chessboard(boardId, config);
    ensureSquareIds(boardId, 20);

    // Keep ids stable if chessboard.js rebuilds its DOM.
    try {
      const boardEl = document.getElementById(boardId);
      if (boardEl && window.MutationObserver) {
        const obs = new MutationObserver(() => assignSquareIds(boardId));
        obs.observe(boardEl, { childList: true, subtree: true });
      }
    } catch (e) {
      // no-op
    }
  }

  function initAllBoards() {
    const wrappers = document.querySelectorAll('.chessboard-wrapper[data-board-id]');
    wrappers.forEach(initOneBoard);
  }

  window.normalizePlacementFen = normalizePlacementFen;
  window.assignSquareIds = assignSquareIds;
  window.updateChessboardPosition = function(boardId, fenLike) {
    updateChessboardPosition(boardId, fenLike, 0);
  };
  window.initAllChessboards = initAllBoards;

  window.addEventListener('load', () => {
    initAllBoards();
    window.addEventListener('resize', () => {
      const wrappers = document.querySelectorAll('.chessboard-wrapper[data-board-id]');
      wrappers.forEach(w => {
        const boardId = w.getAttribute('data-board-id');
        const board = boardId ? window[boardId] : null;
        if (board && typeof board.resize === 'function') {
          board.resize();
          ensureSquareIds(boardId, 10);
        }
      });
    });
  });
})();


