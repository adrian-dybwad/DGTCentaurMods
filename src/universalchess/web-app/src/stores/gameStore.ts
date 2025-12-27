import { create } from 'zustand';
import type { GameState, AnalysisResult } from '../types/game';

interface GameStoreState {
  gameState: GameState | null;
  connected: boolean;
  analysis: AnalysisResult | null;
  analysisHistory: AnalysisResult[];
  currentMoveIndex: number;
  
  setGameState: (state: GameState) => void;
  setConnected: (connected: boolean) => void;
  setAnalysis: (analysis: AnalysisResult) => void;
  addAnalysisToHistory: (analysis: AnalysisResult) => void;
  setCurrentMoveIndex: (index: number) => void;
  clearAnalysisHistory: () => void;
}

export const useGameStore = create<GameStoreState>((set) => ({
  gameState: null,
  connected: false,
  analysis: null,
  analysisHistory: [],
  currentMoveIndex: -1,

  setGameState: (gameState) => set({ gameState }),
  setConnected: (connected) => set({ connected }),
  setAnalysis: (analysis) => set({ analysis }),
  addAnalysisToHistory: (analysis) =>
    set((state) => ({
      analysisHistory: [...state.analysisHistory, analysis],
    })),
  setCurrentMoveIndex: (currentMoveIndex) => set({ currentMoveIndex }),
  clearAnalysisHistory: () => set({ analysisHistory: [], currentMoveIndex: -1 }),
}));

