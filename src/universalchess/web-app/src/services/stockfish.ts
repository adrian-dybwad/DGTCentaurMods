import type { AnalysisResult } from '../types/game';

/**
 * Stockfish web worker wrapper for chess analysis.
 * 
 * The stockfish.js file must be served from /stockfish/stockfish.js
 * In development, this is proxied to the Flask backend.
 */
export class StockfishService {
  private worker: Worker | null = null;
  private isReady = false;
  private initPromise: Promise<void> | null = null;
  private pendingResolve: ((result: AnalysisResult) => void) | null = null;
  private currentFen = '';
  private currentResult: Partial<AnalysisResult> = {};
  private workerPath: string;

  constructor(workerPath = '/stockfish/stockfish.js') {
    this.workerPath = workerPath;
  }

  /**
   * Initialize Stockfish worker. Safe to call multiple times.
   */
  async init(): Promise<void> {
    // Return existing promise if already initializing
    if (this.initPromise) {
      return this.initPromise;
    }

    // Already initialized
    if (this.worker && this.isReady) {
      return Promise.resolve();
    }

    this.initPromise = this.doInit();
    return this.initPromise;
  }

  private async doInit(): Promise<void> {
    return new Promise((resolve, reject) => {
      try {
        console.log(`[Stockfish] Loading worker from: ${this.workerPath}`);
        this.worker = new Worker(this.workerPath);
        
        this.worker.onmessage = (e) => this.handleMessage(e.data);
        
        this.worker.onerror = (e) => {
          console.error('[Stockfish] Worker error:', e);
          this.initPromise = null;
          reject(new Error(`Stockfish worker failed to load: ${e.message}`));
        };

        // Initialize UCI
        this.worker.postMessage('uci');
        
        // Wait for uciok with timeout
        const timeout = setTimeout(() => {
          if (!this.isReady) {
            console.error('[Stockfish] Init timeout - never received uciok');
            this.initPromise = null;
            reject(new Error('Stockfish init timeout'));
          }
        }, 10000);

        // Poll for ready state
        const checkReady = setInterval(() => {
          if (this.isReady) {
            clearInterval(checkReady);
            clearTimeout(timeout);
            console.log('[Stockfish] Ready');
            resolve();
          }
        }, 100);
      } catch (e) {
        console.error('[Stockfish] Init failed:', e);
        this.initPromise = null;
        reject(e);
      }
    });
  }

  private handleMessage(line: string): void {
    if (line === 'uciok') {
      this.isReady = true;
      this.worker?.postMessage('isready');
      return;
    }

    if (line === 'readyok') {
      return;
    }

    // Parse score
    if (line.startsWith('info') && line.includes('score')) {
      const cpMatch = line.match(/score cp (-?\d+)/);
      const mateMatch = line.match(/score mate (-?\d+)/);
      const depthMatch = line.match(/depth (\d+)/);

      if (cpMatch) {
        this.currentResult.score = parseInt(cpMatch[1], 10);
        this.currentResult.mate = null;
      }
      if (mateMatch) {
        this.currentResult.mate = parseInt(mateMatch[1], 10);
        this.currentResult.score = null;
      }
      if (depthMatch) {
        this.currentResult.depth = parseInt(depthMatch[1], 10);
      }
    }

    // Parse bestmove
    if (line.startsWith('bestmove')) {
      const match = line.match(/bestmove (\S+)/);
      if (match) {
        this.currentResult.bestMove = match[1];
      }

      if (this.pendingResolve) {
        this.pendingResolve({
          fen: this.currentFen,
          score: this.currentResult.score ?? null,
          mate: this.currentResult.mate ?? null,
          bestMove: this.currentResult.bestMove ?? null,
          depth: this.currentResult.depth ?? 0,
        });
        this.pendingResolve = null;
      }
    }
  }

  /**
   * Analyze a position. Initializes Stockfish if not already done.
   */
  async analyze(fen: string, depth = 18): Promise<AnalysisResult> {
    // Auto-init if needed
    if (!this.isReady) {
      await this.init();
    }

    if (!this.worker) {
      throw new Error('Stockfish worker not available');
    }

    // Cancel any pending analysis
    this.worker.postMessage('stop');

    this.currentFen = fen;
    this.currentResult = {};

    return new Promise((resolve) => {
      this.pendingResolve = resolve;
      this.worker!.postMessage(`position fen ${fen}`);
      this.worker!.postMessage(`go depth ${depth}`);
    });
  }

  /**
   * Check if Stockfish is ready.
   */
  get ready(): boolean {
    return this.isReady;
  }

  stop(): void {
    this.worker?.postMessage('stop');
  }

  destroy(): void {
    this.worker?.terminate();
    this.worker = null;
    this.isReady = false;
    this.initPromise = null;
  }
}

// Singleton instance
let instance: StockfishService | null = null;

export function getStockfishService(): StockfishService {
  if (!instance) {
    instance = new StockfishService();
  }
  return instance;
}
