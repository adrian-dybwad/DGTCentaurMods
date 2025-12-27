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
    const squaresReady = boardEl.querySelectorAll('div[class*="square-"]').length >= 64;
    if (!squaresReady) return false;
    // chessboard.js also relies on layout. If the element isn't measurable yet,
    // `position()` can throw internally. Guard with a size check.
    const rect = boardEl.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
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
      if (tries < 60) {
        setTimeout(() => updateChessboardPosition(boardId, placement, tries + 1), 50);
      }
      return;
    }

    try {
      board.position(placement);
      ensureSquareIds(boardId, 10);
    } catch (e) {
      if (tries < 60) {
        setTimeout(() => updateChessboardPosition(boardId, placement, tries + 1), 50);
        return;
      }
      console.error('Failed to update board position:', e);
    }
  }

  function initOneBoard(wrapper, retryCount) {
    const boardId = wrapper.getAttribute('data-board-id');
    if (!boardId) return;
    if (window[boardId]) return; // Already initialized.

    const tries = typeof retryCount === 'number' ? retryCount : 0;

    // chessboard.js requires jQuery. Wait for both.
    if (typeof window.jQuery === 'undefined' || typeof window.Chessboard !== 'function') {
      if (tries < 50) {
        setTimeout(() => initOneBoard(wrapper, tries + 1), 100);
      } else {
        console.error('jQuery or Chessboard() not available after 5s. Check script loading.');
      }
      return;
    }

    const fenRaw = wrapper.getAttribute('data-fen') || '';
    const placement = normalizePlacementFen(fenRaw) || 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR';
    const pieceTheme = wrapper.getAttribute('data-piece-theme');

    const config = {
      position: placement,
      pieceTheme: pieceTheme || undefined,
    };

    try {
      window[boardId] = window.Chessboard(boardId, config);
    } catch (e) {
      console.error('Chessboard() threw:', e);
      if (tries < 50) {
        setTimeout(() => initOneBoard(wrapper, tries + 1), 100);
      }
      return;
    }
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
    const wrappers = document.querySelectorAll('[data-board-id]');
    wrappers.forEach(w => initOneBoard(w, 0));
    // Notify dependents (SSE client, analysis) that boards exist now.
    window.dispatchEvent(new CustomEvent('chessboardsReady'));
  }

  function showBoardInitError(boardId, message) {
    const boardEl = document.getElementById(boardId);
    if (!boardEl) return;
    const existing = document.getElementById(boardId + '-init-error');
    if (existing) return;
    const banner = document.createElement('div');
    banner.id = boardId + '-init-error';
    banner.style.cssText = 'padding:12px;margin:8px 0;border:1px solid #f14668;background:#fff5f7;color:#cc0f35;border-radius:6px;font-size:14px;';
    banner.textContent = message;
    boardEl.parentElement && boardEl.parentElement.prepend(banner);
  }

  function verifyBoardsRendered(attempt) {
    const tries = typeof attempt === 'number' ? attempt : 0;
    const wrappers = document.querySelectorAll('[data-board-id]');
    let allGood = true;

    wrappers.forEach(w => {
      const boardId = w.getAttribute('data-board-id');
      if (!boardId) return;
      const boardEl = document.getElementById(boardId);
      const squares = boardEl ? boardEl.querySelectorAll('div[class*="square-"]').length : 0;
      if (squares < 64) {
        allGood = false;
        // Retry init in case scripts raced or the board was initialized before dependencies loaded.
        initOneBoard(w);
      }
    });

    if (allGood) return;
    if (tries < 20) {
      setTimeout(() => verifyBoardsRendered(tries + 1), 250);
      return;
    }

    // Still not good: surface a visible error with diagnostics.
    wrappers.forEach(w => {
      const boardId = w.getAttribute('data-board-id');
      if (!boardId) return;
      const boardEl = document.getElementById(boardId);
      const squares = boardEl ? boardEl.querySelectorAll('div[class*="square-"]').length : 0;
      if (squares < 64) {
        const hasJQuery = typeof window.jQuery !== 'undefined';
        const hasChessboard = typeof window.Chessboard === 'function';
        const boardInstance = window[boardId];
        const diag = `jQuery: ${hasJQuery}, Chessboard: ${hasChessboard}, instance: ${!!boardInstance}, squares: ${squares}`;
        console.error('Board init failed:', diag);
        showBoardInitError(
          boardId,
          `Chessboard failed to initialize. Diagnostics: ${diag}`
        );
      }
    });
  }

  window.normalizePlacementFen = normalizePlacementFen;
  window.assignSquareIds = assignSquareIds;
  window.updateChessboardPosition = function(boardId, fenLike) {
    updateChessboardPosition(boardId, fenLike, 0);
  };
  window.initAllChessboards = initAllBoards;

  function initWhenReady() {
    initAllBoards();
    verifyBoardsRendered(0);
    window.addEventListener('resize', () => {
      const wrappers = document.querySelectorAll('[data-board-id]');
      wrappers.forEach(w => {
        const boardId = w.getAttribute('data-board-id');
        const board = boardId ? window[boardId] : null;
        if (board && typeof board.resize === 'function') {
          board.resize();
          ensureSquareIds(boardId, 10);
        }
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initWhenReady);
  } else {
    // Script is loaded late (end of body); DOM is already ready.
    initWhenReady();
  }
})();


