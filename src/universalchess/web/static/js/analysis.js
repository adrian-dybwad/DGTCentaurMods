/**
 * analysis.js - Shared Stockfish analysis engine and move navigation
 * 
 * This module provides:
 * - Stockfish worker management
 * - Position analysis with eval scores
 * - Eval history chart management
 * - Move navigation (first/prev/next/last)
 * - Live mode with new-move toast notifications
 * 
 * Usage:
 *   // Initialize with options
 *   analysisEngine.init({
 *     mode: 'live',  // or 'static'
 *     containerId: 'analysis',  // prefix for element IDs
 *     onPositionChange: (fen, moveNum) => { board.position(fen); }
 *   });
 *   
 *   // Load a PGN for analysis
 *   analysisEngine.loadPgn(pgnString);
 *   
 *   // For live mode, call on new game state
 *   analysisEngine.onGameStateUpdate(state);
 */

const analysisEngine = (function() {
  'use strict';
  
  // Configuration
  let config = {
    mode: 'live',           // 'live' or 'static'
    containerId: 'analysis',
    stockfishPath: '/static/stockfish/stockfish.js',
    liveDepth: 15,          // Depth for live/current position analysis
    queueDepth: 10,         // Depth for batch replay analysis
    onPositionChange: null, // Callback: (fen, moveNumber) => void
    debug: false,           // Enables verbose console logging
  };
  
  // State
  let chess = null;           // Chess.js instance for game state
  let moves = [];             // Array of SAN moves
  let movePos = 0;            // Current position in move list (0 = start)
  let totalMoves = 0;         // Total moves in the game
  let evalHistory = [];       // Array of {moveNum, eval} for chart
  let stockfish = null;       // Web Worker
  let chart = null;           // Chart.js instance
  
  // Analysis state
  let currentAnalysisFen = null;
  let lastEvalScore = 0;
  let bestMoveUci = '';
  let isQueuedAnalysis = false;
  let queuedMoveNumber = 0;
  let analysisQueue = [];
  let isProcessingQueue = false;
  let pendingGameState = null; // Buffer for live state received before init()
  
  // Live mode state
  let latestGameState = null;
  let latestMoveNumber = 0;
  let unseenMoves = 0;
  let lastSeenPgn = '';
  
  function debugLog(...args) {
    if (config.debug) {
      console.log(...args);
    }
  }

  // --- Initialization ---
  
  function init(options) {
    Object.assign(config, options);
    
    // Initialize chess.js
    if (typeof Chess !== 'undefined') {
      chess = new Chess();
    } else {
      console.error('[Analysis] Chess.js not loaded!');
      return;
    }
    
    initChart();
    initStockfish();

    // If a live update arrived before init() completed, replay it now.
    if (pendingGameState) {
      const state = pendingGameState;
      pendingGameState = null;
      onGameStateUpdate(state);
    }
    
    // Set up SSE listener for live mode
    if (config.mode === 'live') {
      window.addEventListener('gameStateUpdate', function(event) {
        onGameStateUpdate(event.detail);
      });
    }
  }
  
  function initChart() {
    const ctx = document.getElementById(config.containerId + '-chart');
    if (!ctx) {
      console.warn('[Analysis] Chart canvas not found:', config.containerId + '-chart');
      return;
    }
    
    chart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: [],
        datasets: [{
          label: 'Eval',
          data: [],
          fill: true,
          borderColor: 'rgb(150, 150, 150)',
          borderWidth: 1,
          lineTension: 0.4,
          backgroundColor: 'rgba(150, 150, 150, 0.3)',
          pointRadius: function(context) {
            // Highlight current position
            return context.dataIndex === movePos - 1 ? 6 : 3;
          },
          pointBackgroundColor: function(context) {
            return context.dataIndex === movePos - 1 ? '#aa44aa' : 'rgba(255, 255, 255, 1)';
          }
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        title: { display: false },
        legend: { display: false },
        layout: { padding: { bottom: 0 } },
        onClick: function(evt, elements) {
          if (elements.length > 0) {
            const index = elements[0]._index;
            goToMove(index + 1);
          }
        },
        scales: {
          yAxes: [{
            display: true,
            ticks: {
              min: -500,
              max: 500,
              stepSize: 250,
              callback: function(value) {
                return (value / 100).toFixed(0);
              }
            },
            gridLines: { display: true, color: 'rgba(200,200,200,0.3)' }
          }],
          xAxes: [{
            display: false,
            gridLines: { display: false }
          }]
        },
        tooltips: {
          callbacks: {
            title: function(items) {
              return 'Move ' + (items[0].index + 1);
            },
            label: function(tooltipItem) {
              const cp = tooltipItem.yLabel;
              return (cp / 100).toFixed(2) + ' pawns';
            }
          }
        }
      }
    });
  }
  
  function initStockfish() {
    if (stockfish) return;
    
    try {
      debugLog('[Analysis] Initializing Stockfish worker');
      stockfish = new Worker(config.stockfishPath);
      
      stockfish.onmessage = function(event) {
        const line = event.data;
        
        // When Stockfish is ready, process any queued positions
        if (line === 'uciok') {
          debugLog('[Analysis] Stockfish ready');
          if (analysisQueue.length > 0 && !isProcessingQueue) {
            debugLog('[Analysis] Processing', analysisQueue.length, 'queued positions');
            processNextInQueue();
          }
        }
        
        handleStockfishMessage(line);
      };
      
      stockfish.postMessage('uci');
    } catch (e) {
      console.error('[Analysis] Failed to initialize Stockfish:', e);
    }
  }
  
  // --- Stockfish Message Handling ---
  
  function handleStockfishMessage(line) {
    // Parse evaluation from "info" lines
    if (line.indexOf('score cp') > 0) {
      const cpMatch = line.match(/score cp (-?\d+)/);
      if (cpMatch) {
        let cp = parseInt(cpMatch[1]);
        // Negate if black's turn (eval from white's perspective)
        if (currentAnalysisFen && currentAnalysisFen.includes(' b ')) {
          cp = -cp;
        }
        lastEvalScore = cp;
        if (!isQueuedAnalysis) {
          updateEvalBar(cp);
        }
      }
    }
    
    // Parse mate score
    if (line.indexOf('score mate') > 0) {
      const mateMatch = line.match(/score mate (-?\d+)/);
      if (mateMatch) {
        let mateIn = parseInt(mateMatch[1]);
        if (currentAnalysisFen && currentAnalysisFen.includes(' b ')) {
          mateIn = -mateIn;
        }
        lastEvalScore = mateIn > 0 ? 10000 : -10000;
        if (!isQueuedAnalysis) {
          updateEvalBar(lastEvalScore);
          updateEvalDisplay(null, mateIn);
        }
      }
    }
    
    // Parse best move - analysis complete for this position
    if (line.indexOf('bestmove ') === 0) {
      bestMoveUci = line.split(' ')[1];
      
      if (isQueuedAnalysis) {
        // Batch analysis - add to history and continue queue
        if (queuedMoveNumber > 0) {
          addEvalToHistory(queuedMoveNumber, lastEvalScore);
        }
        processNextInQueue();
      } else {
        // Live/current analysis
        updateEvalDisplay(bestMoveUci, null);
        if (movePos > 0) {
          addEvalToHistory(movePos, lastEvalScore);
        }
      }
    }
  }
  
  // --- Analysis Queue ---
  
  function processNextInQueue() {
    if (analysisQueue.length === 0) {
      isProcessingQueue = false;
      debugLog('[Analysis] Queue processing complete');
      // Analyze current position at full depth
      if (chess && movePos > 0) {
        analyzeCurrentPosition();
      }
      return;
    }
    
    isProcessingQueue = true;
    const next = analysisQueue.shift();
    analyzePositionQueued(next.fen, next.moveNum);
  }
  
  function analyzePositionQueued(fen, moveNumber) {
    if (!stockfish || !fen) {
      processNextInQueue();
      return;
    }
    
    isQueuedAnalysis = true;
    queuedMoveNumber = moveNumber;
    currentAnalysisFen = fen;

    // Ensure any previous analysis is stopped before starting queued replay work.
    // Without this, Stockfish can keep running the previous `go` command and ignore
    // subsequent `position`/`go` messages, which prevents history from populating.
    stockfish.postMessage('stop');
    stockfish.postMessage('position fen ' + fen);
    stockfish.postMessage('go depth ' + config.queueDepth);
  }
  
  function analyzeCurrentPosition() {
    if (!stockfish || !chess) return;
    
    const fen = chess.fen();
    if (!fen || fen === currentAnalysisFen) return;
    
    isQueuedAnalysis = false;
    currentAnalysisFen = fen;
    bestMoveUci = '';
    
    stockfish.postMessage('stop');
    stockfish.postMessage('position fen ' + fen);
    stockfish.postMessage('go depth ' + config.liveDepth);
  }
  
  // --- PGN Loading ---
  
  function loadPgn(pgn) {
    if (!pgn || !chess) {
      return false;
    }
    debugLog('[Analysis] loadPgn called, pgn length:', pgn.length);
    
    // Reset state
    chess.reset();
    moves = [];
    movePos = 0;
    totalMoves = 0;
    evalHistory = [];
    analysisQueue = [];
    isProcessingQueue = false;
    lastSeenPgn = pgn;
    
    // Clear chart
    if (chart) {
      chart.data.labels = [];
      chart.data.datasets[0].data = [];
      chart.update();
    }
    
    // Try to load the PGN
    const tempChess = new Chess();
    if (!tempChess.load_pgn(pgn)) {
      console.error('[Analysis] Could not parse PGN');
      return false;
    }
    
    moves = tempChess.history();
    totalMoves = moves.length;
    debugLog('[Analysis] Loaded', totalMoves, 'moves');
    
    if (totalMoves === 0) {
      debugLog('[Analysis] No moves in PGN');
      updateMoveIndicator();
      return true;
    }
    
    // Queue all positions for analysis
    tempChess.reset();
    for (let i = 0; i < moves.length; i++) {
      tempChess.move(moves[i]);
      analysisQueue.push({ fen: tempChess.fen(), moveNum: i + 1 });
    }
    debugLog('[Analysis] Queued', analysisQueue.length, 'positions for analysis');
    
    // Reset to start position
    chess.reset();
    movePos = 0;
    updateMoveIndicator();
    
    // Start batch analysis - ensure stockfish is ready
    if (analysisQueue.length > 0 && stockfish) {
      debugLog('[Analysis] Starting queue processing');
      processNextInQueue();
    } else if (!stockfish) {
      debugLog('[Analysis] Stockfish not ready, will analyze when initialized');
    }
    
    // Notify position change
    notifyPositionChange();
    
    return true;
  }
  
  // --- Live Mode ---
  
  function onGameStateUpdate(state) {
    if (!state) return;
    
    latestGameState = state;

    // If init() hasn't run yet, buffer the latest state and retry after init.
    if (!chess) {
      pendingGameState = state;
      return;
    }

    const newMoveNumber = state.move_number || 0;
    
    // Detect new game
    if (newMoveNumber === 1 && latestMoveNumber > 1) {
      resetForNewGame();
    }
    
    // Initial load: if we have a PGN but haven't loaded it yet
    if (state.pgn && lastSeenPgn === '' && totalMoves === 0) {
      debugLog('[Analysis] Initial PGN load, move_number:', newMoveNumber);
      latestMoveNumber = newMoveNumber;
      if (loadPgn(state.pgn)) {
        // Go to the last move to show current position
        goToMove(totalMoves);
      }
      return;
    }
    
    // Check for new moves (game in progress)
    if (newMoveNumber > latestMoveNumber) {
      latestMoveNumber = newMoveNumber;
      
      // Load updated PGN if changed
      if (state.pgn && state.pgn !== lastSeenPgn) {
        const wasAtEnd = movePos === totalMoves;
        loadPgn(state.pgn);
        
        if (wasAtEnd) {
          // User was following along, keep them at the end
          goToMove(totalMoves);
        } else {
          // User is reviewing history, show toast for unseen moves
          unseenMoves = totalMoves - movePos;
          showNewMovesToast(unseenMoves);
        }
      }
    }
  }
  
  function resetForNewGame() {
    chess.reset();
    moves = [];
    movePos = 0;
    totalMoves = 0;
    evalHistory = [];
    analysisQueue = [];
    lastSeenPgn = '';
    latestMoveNumber = 0;
    unseenMoves = 0;
    hideNewMovesToast();
    
    if (chart) {
      chart.data.labels = [];
      chart.data.datasets[0].data = [];
      chart.update();
    }
    
    updateMoveIndicator();
    notifyPositionChange();
  }
  
  // --- Navigation ---
  
  function goToMove(targetMove) {
    if (!chess || targetMove < 0 || targetMove > totalMoves) return;
    
    // Reset to start
    chess.reset();
    movePos = 0;
    
    // Replay to target position
    for (let i = 0; i < targetMove && i < moves.length; i++) {
      chess.move(moves[i]);
      movePos++;
    }
    
    updateMoveIndicator();
    updateChartHighlight();
    notifyPositionChange();
    // Do not interrupt queued replay analysis. The queue exists to populate the
    // history chart; cancelling it prevents the chart from ever filling.
    // Once the queue completes, it triggers a full-depth analysis of the current
    // position automatically.
    if (!isProcessingQueue) {
      analyzeCurrentPosition();
    }
    
    // Hide toast if we caught up
    if (movePos >= totalMoves) {
      unseenMoves = 0;
      hideNewMovesToast();
    }
  }
  
  function first() {
    goToMove(0);
  }
  
  function prev() {
    goToMove(movePos - 1);
  }
  
  function next() {
    goToMove(movePos + 1);
  }
  
  function last() {
    goToMove(totalMoves);
  }
  
  function jumpToLatest() {
    goToMove(totalMoves);
    unseenMoves = 0;
    hideNewMovesToast();
  }
  
  // --- UI Updates ---
  
  function updateMoveIndicator() {
    const indicator = document.getElementById(config.containerId + '-move-indicator');
    if (indicator) {
      indicator.textContent = movePos + '/' + totalMoves;
    }
  }
  
  function updateChartHighlight() {
    if (chart) {
      chart.update();
    }
  }
  
  function updateEvalBar(cp) {
    const bar = document.getElementById(config.containerId + '-eval-bar');
    if (!bar) return;
    
    // Clamp to +/- 10 pawns, map to 0-100
    let clampedCp = Math.max(-1000, Math.min(1000, cp));
    let barValue = 50 - (clampedCp / 20);
    bar.value = barValue;
    
    // Color based on who's winning
    if (cp > 100) {
      bar.className = 'progress is-success';
    } else if (cp < -100) {
      bar.className = 'progress is-danger';
    } else {
      bar.className = 'progress is-warning';
    }
  }
  
  function updateEvalDisplay(bestMove, mateIn) {
    const scoreEl = document.getElementById(config.containerId + '-eval-score');
    const moveEl = document.getElementById(config.containerId + '-best-move');
    
    if (scoreEl) {
      if (mateIn !== null) {
        scoreEl.textContent = mateIn > 0 ? 'M' + mateIn : 'M' + (-mateIn);
        scoreEl.style.color = mateIn > 0 ? 'var(--color-success, green)' : 'var(--color-danger, red)';
      } else {
        const pawns = (lastEvalScore / 100).toFixed(1);
        scoreEl.textContent = lastEvalScore >= 0 ? '+' + pawns : pawns;
        scoreEl.style.color = '';
      }
    }
    
    if (moveEl) {
      moveEl.innerHTML = bestMove ? 'Best: <strong>' + bestMove + '</strong>' : 'Analyzing...';
    }
  }
  
  function addEvalToHistory(moveNum, evalCp) {
    const clampedEval = Math.max(-500, Math.min(500, evalCp));
    
    // Update existing or add new
    const existingIndex = evalHistory.findIndex(e => e.moveNum === moveNum);
    if (existingIndex >= 0) {
      evalHistory[existingIndex].eval = clampedEval;
    } else {
      evalHistory.push({ moveNum, eval: clampedEval });
      evalHistory.sort((a, b) => a.moveNum - b.moveNum);
    }
    
    // Update chart
    if (chart) {
      chart.data.labels = evalHistory.map(e => e.moveNum);
      chart.data.datasets[0].data = evalHistory.map(e => e.eval);
      chart.update();
    }
  }
  
  function showNewMovesToast(count) {
    const toast = document.getElementById(config.containerId + '-new-moves-toast');
    const countEl = document.getElementById(config.containerId + '-new-moves-count');
    if (toast && countEl) {
      countEl.textContent = count;
      toast.style.display = 'block';
    }
  }
  
  function hideNewMovesToast() {
    const toast = document.getElementById(config.containerId + '-new-moves-toast');
    if (toast) {
      toast.style.display = 'none';
    }
  }
  
  function notifyPositionChange() {
    if (config.onPositionChange && chess) {
      config.onPositionChange(chess.fen(), movePos);
    }
    
    // Dispatch event for other listeners
    window.dispatchEvent(new CustomEvent('analysisPositionChange', {
      detail: { fen: chess ? chess.fen() : null, moveNumber: movePos }
    }));
  }
  
  // --- Public API ---
  
  return {
    init: init,
    loadPgn: loadPgn,
    onGameStateUpdate: onGameStateUpdate,
    goToMove: goToMove,
    first: first,
    prev: prev,
    next: next,
    last: last,
    jumpToLatest: jumpToLatest,
    getCurrentFen: function() { return chess ? chess.fen() : null; },
    getMovePos: function() { return movePos; },
    getTotalMoves: function() { return totalMoves; },
    getEvalHistory: function() { return evalHistory.slice(); }
  };
})();

// Navigation shortcuts for use in onclick handlers
const analysisNav = {
  first: function() { analysisEngine.first(); },
  prev: function() { analysisEngine.prev(); },
  next: function() { analysisEngine.next(); },
  last: function() { analysisEngine.last(); },
  jumpToLatest: function() { analysisEngine.jumpToLatest(); }
};

