import { create } from 'zustand';
import api from '../api';

const useVODStore = create((set, get) => ({
  movies: {},
  series: {},
  episodes: {},
  categories: {},
  loading: false,
  error: null,
  filters: {
    type: 'all', // 'all', 'movies', 'series'
    search: '',
    category: '',
  },
  currentPage: 1,
  totalCount: 0,
  pageSize: 24,

  setFilters: (newFilters) =>
    set((state) => ({
      filters: { ...state.filters, ...newFilters },
      currentPage: 1, // Reset to first page when filters change
    })),

  setPage: (page) =>
    set(() => ({
      currentPage: page,
    })),

  setPageSize: (size) =>
    set(() => ({
      pageSize: size,
      currentPage: 1, // Reset to first page when page size changes
    })),

  fetchMovies: async () => {
    try {
      set({ loading: true, error: null });
      const state = get();
      const params = new URLSearchParams();

      params.append('page', state.currentPage);
      params.append('page_size', state.pageSize);

      if (state.filters.search) {
        params.append('search', state.filters.search);
      }

      if (state.filters.category) {
        params.append('category', state.filters.category);
      }

      const response = await api.getMovies(params);

      // Handle both paginated and non-paginated responses
      const results = response.results || response;
      const count = response.count || results.length;

      set({
        movies: results.reduce((acc, movie) => {
          acc[movie.id] = movie;
          return acc;
        }, {}),
        totalCount: count,
        loading: false,
      });
    } catch (error) {
      console.error('Failed to fetch movies:', error);
      set({ error: 'Failed to load movies.', loading: false });
    }
  },

  fetchSeries: async () => {
    set({ loading: true, error: null });
    try {
      const state = get();
      const params = new URLSearchParams();

      params.append('page', state.currentPage);
      params.append('page_size', state.pageSize);

      if (state.filters.search) {
        params.append('search', state.filters.search);
      }

      if (state.filters.category) {
        params.append('category', state.filters.category);
      }

      const response = await api.getSeries(params);

      // Handle both paginated and non-paginated responses
      const results = response.results || response;
      const count = response.count || results.length;

      set({
        series: results.reduce((acc, series) => {
          acc[series.id] = series;
          return acc;
        }, {}),
        totalCount: count,
        loading: false,
      });
    } catch (error) {
      console.error('Failed to fetch series:', error);
      set({ error: 'Failed to load series.', loading: false });
    }
  },

  fetchSeriesEpisodes: async (seriesId) => {
    set({ loading: true, error: null });
    try {
      const response = await api.getSeriesEpisodes(seriesId);

      set((state) => ({
        episodes: {
          ...state.episodes,
          ...response.reduce((acc, episode) => {
            acc[episode.id] = episode;
            return acc;
          }, {}),
        },
        loading: false,
      }));

      return response;
    } catch (error) {
      console.error('Failed to fetch series episodes:', error);
      set({ error: 'Failed to load episodes.', loading: false });
      throw error; // Re-throw to allow calling component to handle
    }
  },

  fetchMovieDetails: async (movieId) => {
    set({ loading: true, error: null });
    try {
      const response = await api.getMovieDetails(movieId);

      // Transform the response data to match our expected format
      const movieDetails = {
        id: response.id || movieId,
        name: response.name || '',
        description: response.description || '',
        year: response.year || null,
        genre: response.genre || '',
        rating: response.rating || '',
        duration_secs: response.duration_secs || null,
        stream_url: response.url || '',
        logo: response.logo_url || null,
        type: 'movie',
        director: response.director || '',
        actors: response.actors || '',
        country: response.country || '',
        tmdb_id: response.tmdb_id || '',
        imdb_id: response.imdb_id || '',
        m3u_account: response.m3u_account || '',
      };
      console.log('Fetched Movie Details:', movieDetails);
      set((state) => ({
        movies: {
          ...state.movies,
          [movieDetails.id]: movieDetails,
        },
        loading: false,
      }));

      return movieDetails;
    } catch (error) {
      console.error('Failed to fetch movie details:', error);
      set({ error: 'Failed to load movie details.', loading: false });
      throw error;
    }
  },

  fetchMovieDetailsFromProvider: async (movieId) => {
    set({ loading: true, error: null });
    try {
      const response = await api.getMovieProviderInfo(movieId);

      // Transform the response data to match our expected format
      const movieDetails = {
        id: response.id || movieId,
        name: response.name || '',
        description: response.description || response.plot || '',
        year: response.year || null,
        genre: response.genre || '',
        rating: response.rating || '',
        duration_secs: response.duration_secs || null,
        stream_url: response.stream_url || '',
        logo: response.logo || response.cover || null,
        type: 'movie',
        director: response.director || '',
        actors: response.actors || response.cast || '',
        country: response.country || '',
        tmdb_id: response.tmdb_id || '',
        youtube_trailer: response.youtube_trailer || '',
        // Additional provider fields
        backdrop_path: response.backdrop_path || [],
        release_date: response.release_date || response.releasedate || '',
        movie_image: response.movie_image || null,
        o_name: response.o_name || '',
        age: response.age || '',
        episode_run_time: response.episode_run_time || null,
        bitrate: response.bitrate || 0,
        video: response.video || {},
        audio: response.audio || {},
      };

      set({ loading: false }); // Only update loading state

      // Do NOT merge or overwrite the store entry
      return movieDetails;
    } catch (error) {
      console.error('Failed to fetch movie details from provider:', error);
      set({
        error: 'Failed to load movie details from provider.',
        loading: false,
      });
      throw error;
    }
  },

  fetchMovieProviders: async (movieId) => {
    try {
      const response = await api.getMovieProviders(movieId);
      return response || [];
    } catch (error) {
      console.error('Failed to fetch movie providers:', error);
      throw error;
    }
  },

  fetchSeriesProviders: async (seriesId) => {
    try {
      const response = await api.getSeriesProviders(seriesId);
      return response || [];
    } catch (error) {
      console.error('Failed to fetch series providers:', error);
      throw error;
    }
  },

  fetchCategories: async () => {
    try {
      const response = await api.getVODCategories();
      // Handle both array and paginated responses
      const results = response.results || response;

      set({
        categories: results.reduce((acc, category) => {
          acc[category.id] = category;
          return acc;
        }, {}),
      });
    } catch (error) {
      console.error('Failed to fetch VOD categories:', error);
      set({ error: 'Failed to load categories.' });
    }
  },

  addMovie: (movie) =>
    set((state) => ({
      movies: { ...state.movies, [movie.id]: movie },
    })),

  updateMovie: (movie) =>
    set((state) => ({
      movies: { ...state.movies, [movie.id]: movie },
    })),

  removeMovie: (movieId) =>
    set((state) => {
      const updatedMovies = { ...state.movies };
      delete updatedMovies[movieId];
      return { movies: updatedMovies };
    }),

  addSeries: (series) =>
    set((state) => ({
      series: { ...state.series, [series.id]: series },
    })),

  updateSeries: (series) =>
    set((state) => ({
      series: { ...state.series, [series.id]: series },
    })),

  removeSeries: (seriesId) =>
    set((state) => {
      const updatedSeries = { ...state.series };
      delete updatedSeries[seriesId];
      return { series: updatedSeries };
    }),

  fetchSeriesInfo: async (seriesId) => {
    set({ loading: true, error: null });
    try {
      const response = await api.getSeriesInfo(seriesId);

      // Transform the response data to match our expected format
      const seriesInfo = {
        id: response.id || seriesId,
        name: response.name || '',
        description:
          response.description || response.custom_properties?.plot || '',
        year: response.year || null,
        genre: response.genre || '',
        rating: response.rating || '',
        logo: response.cover || null,
        type: 'series',
        director: response.custom_properties?.director || '',
        cast: response.custom_properties?.cast || '',
        country: response.country || '',
        tmdb_id: response.tmdb_id || '',
        imdb_id: response.imdb_id || '',
        episode_count: response.episode_count || 0,
        // Additional provider fields
        backdrop_path: response.custom_properties?.backdrop_path || [],
        release_date: response.release_date || '',
        series_image: response.series_image || null,
        o_name: response.o_name || '',
        age: response.age || '',
        m3u_account: response.m3u_account || '',
        youtube_trailer: response.custom_properties?.youtube_trailer || '',
      };

      let episodesData = {};

      // Handle episodes - check if they're in the response
      if (response.episodes) {
        Object.entries(response.episodes).forEach(
          ([seasonNumber, seasonEpisodes]) => {
            seasonEpisodes.forEach((episode) => {
              const episodeData = {
                id: episode.id,
                stream_id: episode.id,
                name: episode.title || '',
                description: episode.plot || '',
                season_number: parseInt(seasonNumber) || 0,
                episode_number: episode.episode_number || 0,
                duration_secs: episode.duration_secs || null,
                rating: episode.rating || '',
                container_extension: episode.container_extension || '',
                series: {
                  id: seriesInfo.id,
                  name: seriesInfo.name,
                },
                type: 'episode',
                uuid: episode.id, // Use the stream ID as UUID for playback
                logo: episode.movie_image ? { url: episode.movie_image } : null,
                air_date: episode.air_date || null,
                movie_image: episode.movie_image || null,
                tmdb_id: episode.tmdb_id || '',
                imdb_id: episode.imdb_id || '',
              };
              episodesData[episode.id] = episodeData;
            });
          }
        );

        // Update episodes in the store
        set((state) => ({
          episodes: {
            ...state.episodes,
            ...episodesData,
          },
        }));
      }

      set((state) => ({
        series: {
          ...state.series,
          [seriesInfo.id]: seriesInfo,
        },
        loading: false,
      }));

      // Return series info with episodes array for easy access
      return {
        ...seriesInfo,
        episodesList: Object.values(episodesData),
      };
    } catch (error) {
      console.error('Failed to fetch series info:', error);
      set({ error: 'Failed to load series details.', loading: false });
      throw error;
    }
  },
}));

export default useVODStore;
