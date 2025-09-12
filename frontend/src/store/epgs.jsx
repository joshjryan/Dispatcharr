import { create } from 'zustand';
import api from '../api';

const useEPGsStore = create((set) => ({
  epgs: {},
  tvgs: [],
  tvgsById: {},
  isLoading: false,
  error: null,
  refreshProgress: {},

  fetchEPGs: async () => {
    set({ isLoading: true, error: null });
    try {
      const epgs = await api.getEPGs();
      set({
        epgs: epgs.reduce((acc, epg) => {
          acc[epg.id] = epg;
          return acc;
        }, {}),
        isLoading: false,
      });
    } catch (error) {
      console.error('Failed to fetch epgs:', error);
      set({ error: 'Failed to load epgs.', isLoading: false });
    }
  },

  fetchEPGData: async () => {
    set({ isLoading: true, error: null });
    try {
      const tvgs = await api.getEPGData();
      set({
        tvgs: tvgs,
        tvgsById: tvgs.reduce((acc, tvg) => {
          acc[tvg.id] = tvg;
          return acc;
        }, {}),
        isLoading: false,
      });
    } catch (error) {
      console.error('Failed to fetch tvgs:', error);
      set({ error: 'Failed to load tvgs.', isLoading: false });
    }
  },

  addEPG: (epg) =>
    set((state) => ({
      epgs: { ...state.epgs, [epg.id]: epg },
    })),

  updateEPG: (epg) =>
    set((state) => ({
      epgs: { ...state.epgs, [epg.id]: epg },
    })),

  removeEPGs: (epgIds) =>
    set((state) => {
      const updatedEPGs = { ...state.epgs };
      for (const id of epgIds) {
        delete updatedEPGs[id];
      }

      return { epgs: updatedEPGs };
    }),

  updateEPGProgress: (data) =>
    set((state) => {
      // Early exit if source doesn't exist in our EPGs store
      if (!state.epgs[data.source] && !data.status) {
        return state;
      }

      // Create a new refreshProgress object that includes the current update
      const newRefreshProgress = {
        ...state.refreshProgress,
        [data.source]: {
          action: data.action,
          progress: data.progress,
          speed: data.speed,
          elapsed_time: data.elapsed_time,
          time_remaining: data.time_remaining,
          status: data.status || 'in_progress',
        },
      };

      // Set the EPG source status based on the update
      // First prioritize explicit status values from the backend
      const sourceStatus = data.status
        ? data.status // Use explicit status if provided
        : data.action === 'downloading'
          ? 'fetching'
          : data.action === 'parsing_channels' ||
              data.action === 'parsing_programs'
            ? 'parsing'
            : data.progress === 100
              ? 'success' // Mark as success when progress is 100%
              : state.epgs[data.source]?.status || 'idle';

      // Create a new epgs object with the updated source status
      const newEpgs = {
        ...state.epgs,
        [data.source]: {
          ...state.epgs[data.source],
          status: sourceStatus,
          last_message:
            data.status === 'error'
              ? data.error || 'Unknown error'
              : state.epgs[data.source]?.last_message,
        },
      };

      return {
        refreshProgress: newRefreshProgress,
        epgs: newEpgs,
      };
    }),
}));

export default useEPGsStore;
