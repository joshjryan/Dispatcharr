from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from django.shortcuts import get_object_or_404
import django_filters
import logging
from apps.accounts.permissions import (
    Authenticated,
    permission_classes_by_action,
)
from .models import (
    Series, VODCategory, Movie, Episode,
    M3USeriesRelation, M3UMovieRelation, M3UEpisodeRelation
)
from .serializers import (
    MovieSerializer,
    EpisodeSerializer,
    SeriesSerializer,
    VODCategorySerializer,
    M3UMovieRelationSerializer,
    M3USeriesRelationSerializer,
    M3UEpisodeRelationSerializer
)
from .tasks import refresh_series_episodes, refresh_movie_advanced_data
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)


class VODPagination(PageNumberPagination):
    page_size = 20  # Default page size to match frontend default
    page_size_query_param = "page_size"  # Allow clients to specify page size
    max_page_size = 100  # Prevent excessive page sizes for VOD content


class MovieFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr="icontains")
    m3u_account = django_filters.NumberFilter(field_name="m3u_relations__m3u_account__id")
    category = django_filters.CharFilter(method='filter_category')
    year = django_filters.NumberFilter()
    year_gte = django_filters.NumberFilter(field_name="year", lookup_expr="gte")
    year_lte = django_filters.NumberFilter(field_name="year", lookup_expr="lte")

    class Meta:
        model = Movie
        fields = ['name', 'm3u_account', 'category', 'year']

    def filter_category(self, queryset, name, value):
        """Custom category filter that handles 'name|type' format"""
        if not value:
            return queryset

        # Handle the format 'category_name|category_type'
        if '|' in value:
            category_name, category_type = value.split('|', 1)
            return queryset.filter(
                m3u_relations__category__name=category_name,
                m3u_relations__category__category_type=category_type
            )
        else:
            # Fallback: treat as category name only
            return queryset.filter(m3u_relations__category__name=value)


class MovieViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for Movie content"""
    queryset = Movie.objects.all()
    serializer_class = MovieSerializer
    pagination_class = VODPagination

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = MovieFilter
    search_fields = ['name', 'description', 'genre']
    ordering_fields = ['name', 'year', 'created_at']
    ordering = ['name']

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]

    def get_queryset(self):
        # Only return movies that have active M3U relations
        return Movie.objects.filter(
            m3u_relations__m3u_account__is_active=True
        ).distinct().select_related('logo').prefetch_related('m3u_relations__m3u_account')

    @action(detail=True, methods=['get'], url_path='providers')
    def get_providers(self, request, pk=None):
        """Get all providers (M3U accounts) that have this movie"""
        movie = self.get_object()
        relations = M3UMovieRelation.objects.filter(
            movie=movie,
            m3u_account__is_active=True
        ).select_related('m3u_account', 'category')

        serializer = M3UMovieRelationSerializer(relations, many=True)
        return Response(serializer.data)


    @action(detail=True, methods=['get'], url_path='provider-info')
    def provider_info(self, request, pk=None):
        """Get detailed movie information from the original provider, throttled to 24h."""
        movie = self.get_object()

        # Get the highest priority active relation
        relation = M3UMovieRelation.objects.filter(
            movie=movie,
            m3u_account__is_active=True
        ).select_related('m3u_account').order_by('-m3u_account__priority', 'id').first()

        if not relation:
            return Response(
                {'error': 'No active M3U account associated with this movie'},
                status=status.HTTP_400_BAD_REQUEST
            )

        force_refresh = request.query_params.get('force_refresh', 'false').lower() == 'true'
        now = timezone.now()
        needs_refresh = (
            force_refresh or
            not relation.last_advanced_refresh or
            (now - relation.last_advanced_refresh).total_seconds() > 86400
        )

        if needs_refresh:
            # Trigger advanced data refresh
            logger.debug(f"Refreshing advanced data for movie {movie.id} (relation ID: {relation.id})")
            refresh_movie_advanced_data(relation.id, force_refresh=force_refresh)

            # Refresh objects from database after task completion
            movie.refresh_from_db()
            relation.refresh_from_db()

        # Use refreshed data from database
        custom_props = relation.custom_properties or {}
        info = custom_props.get('detailed_info', {})
        movie_data = custom_props.get('movie_data', {})

        # Build response with available data
        response_data = {
            'id': movie.id,
            'uuid': movie.uuid,
            'stream_id': relation.stream_id,
            'name': info.get('name', movie.name),
            'o_name': info.get('o_name', ''),
            'description': info.get('description', info.get('plot', movie.description)),
            'plot': info.get('plot', info.get('description', movie.description)),
            'year': movie.year or info.get('year'),
            'release_date': (movie.custom_properties or {}).get('release_date') or info.get('release_date') or info.get('releasedate', ''),
            'genre': movie.genre or info.get('genre', ''),
            'director': (movie.custom_properties or {}).get('director') or info.get('director', ''),
            'actors': (movie.custom_properties or {}).get('actors') or info.get('actors', ''),
            'country': (movie.custom_properties or {}).get('country') or info.get('country', ''),
            'rating': movie.rating or info.get('rating', movie.rating or 0),
            'tmdb_id': movie.tmdb_id or info.get('tmdb_id', ''),
            'imdb_id': movie.imdb_id or info.get('imdb_id', ''),
            'youtube_trailer': (movie.custom_properties or {}).get('youtube_trailer') or info.get('youtube_trailer') or info.get('trailer', ''),
            'duration_secs': movie.duration_secs or info.get('duration_secs'),
            'age': info.get('age', ''),
            'backdrop_path': (movie.custom_properties or {}).get('backdrop_path') or info.get('backdrop_path', []),
            'cover': info.get('cover_big', ''),
            'cover_big': info.get('cover_big', ''),
            'movie_image': movie.logo.url if movie.logo else info.get('movie_image', ''),
            'bitrate': info.get('bitrate', 0),
            'video': info.get('video', {}),
            'audio': info.get('audio', {}),
            'container_extension': movie_data.get('container_extension', 'mp4'),
            'direct_source': movie_data.get('direct_source', ''),
            'category_id': movie_data.get('category_id', ''),
            'added': movie_data.get('added', ''),
            'm3u_account': {
                'id': relation.m3u_account.id,
                'name': relation.m3u_account.name,
                'account_type': relation.m3u_account.account_type
            }
        }
        return Response(response_data)

class EpisodeFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr="icontains")
    series = django_filters.NumberFilter(field_name="series__id")
    m3u_account = django_filters.NumberFilter(field_name="m3u_account__id")
    season_number = django_filters.NumberFilter()
    episode_number = django_filters.NumberFilter()

    class Meta:
        model = Episode
        fields = ['name', 'series', 'm3u_account', 'season_number', 'episode_number']


class SeriesFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr="icontains")
    m3u_account = django_filters.NumberFilter(field_name="m3u_relations__m3u_account__id")
    category = django_filters.CharFilter(method='filter_category')
    year = django_filters.NumberFilter()
    year_gte = django_filters.NumberFilter(field_name="year", lookup_expr="gte")
    year_lte = django_filters.NumberFilter(field_name="year", lookup_expr="lte")

    class Meta:
        model = Series
        fields = ['name', 'm3u_account', 'category', 'year']

    def filter_category(self, queryset, name, value):
        """Custom category filter that handles 'name|type' format"""
        if not value:
            return queryset

        # Handle the format 'category_name|category_type'
        if '|' in value:
            category_name, category_type = value.split('|', 1)
            return queryset.filter(
                m3u_relations__category__name=category_name,
                m3u_relations__category__category_type=category_type
            )
        else:
            # Fallback: treat as category name only
            return queryset.filter(m3u_relations__category__name=value)


class EpisodeViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for Episode content"""
    queryset = Episode.objects.all()
    serializer_class = EpisodeSerializer
    pagination_class = VODPagination

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = EpisodeFilter
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'season_number', 'episode_number', 'created_at']
    ordering = ['series__name', 'season_number', 'episode_number']

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]

    def get_queryset(self):
        return Episode.objects.select_related(
            'series', 'm3u_account'
        ).filter(m3u_account__is_active=True)


class SeriesViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for Series management"""
    queryset = Series.objects.all()
    serializer_class = SeriesSerializer
    pagination_class = VODPagination

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = SeriesFilter
    search_fields = ['name', 'description', 'genre']
    ordering_fields = ['name', 'year', 'created_at']
    ordering = ['name']

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]

    def get_queryset(self):
        # Only return series that have active M3U relations
        return Series.objects.filter(
            m3u_relations__m3u_account__is_active=True
        ).distinct().select_related('logo').prefetch_related('episodes', 'm3u_relations__m3u_account')

    @action(detail=True, methods=['get'], url_path='providers')
    def get_providers(self, request, pk=None):
        """Get all providers (M3U accounts) that have this series"""
        series = self.get_object()
        relations = M3USeriesRelation.objects.filter(
            series=series,
            m3u_account__is_active=True
        ).select_related('m3u_account', 'category')

        serializer = M3USeriesRelationSerializer(relations, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='episodes')
    def get_episodes(self, request, pk=None):
        """Get episodes for this series with provider information"""
        series = self.get_object()
        episodes = Episode.objects.filter(series=series).prefetch_related(
            'm3u_relations__m3u_account'
        ).order_by('season_number', 'episode_number')

        episodes_data = []
        for episode in episodes:
            episode_serializer = EpisodeSerializer(episode)
            episode_data = episode_serializer.data

            # Add provider information
            relations = M3UEpisodeRelation.objects.filter(
                episode=episode,
                m3u_account__is_active=True
            ).select_related('m3u_account')

            episode_data['providers'] = M3UEpisodeRelationSerializer(relations, many=True).data
            episodes_data.append(episode_data)

        return Response(episodes_data)

    @action(detail=True, methods=['get'], url_path='provider-info')
    def series_info(self, request, pk=None):
        """Get detailed series information, refreshing from provider if needed"""
        logger.debug(f"SeriesViewSet.series_info called for series ID: {pk}")
        series = self.get_object()
        logger.debug(f"Retrieved series: {series.name} (ID: {series.id})")

        # Get the highest priority active relation
        relation = M3USeriesRelation.objects.filter(
            series=series,
            m3u_account__is_active=True
        ).select_related('m3u_account').order_by('-m3u_account__priority', 'id').first()

        if not relation:
            return Response(
                {'error': 'No active M3U account associated with this series'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Check if we should refresh data (optional force refresh parameter)
            force_refresh = request.query_params.get('force_refresh', 'false').lower() == 'true'
            refresh_interval_hours = int(request.query_params.get("refresh_interval", 24))  # Default to 24 hours

            now = timezone.now()
            last_refreshed = relation.last_episode_refresh

            # Check if detailed data has been fetched
            custom_props = relation.custom_properties or {}
            episodes_fetched = custom_props.get('episodes_fetched', False)
            detailed_fetched = custom_props.get('detailed_fetched', False)

            # Force refresh if episodes have never been fetched or if forced
            if not episodes_fetched or not detailed_fetched or force_refresh:
                force_refresh = True
                logger.debug(f"Series {series.id} needs detailed/episode refresh, forcing refresh")
            elif last_refreshed is None or (now - last_refreshed) > timedelta(hours=refresh_interval_hours):
                force_refresh = True
                logger.debug(f"Series {series.id} refresh interval exceeded or never refreshed, forcing refresh")

            if force_refresh:
                logger.debug(f"Refreshing series {series.id} data from provider")
                # Use existing refresh logic with external_series_id
                from .tasks import refresh_series_episodes
                account = relation.m3u_account
                if account and account.is_active:
                    refresh_series_episodes(account, series, relation.external_series_id)
                    series.refresh_from_db()  # Reload from database after refresh
                    relation.refresh_from_db()  # Reload relation too

            # Return the database data (which should now be fresh)
            custom_props = relation.custom_properties or {}
            response_data = {
                'id': series.id,
                'series_id': relation.external_series_id,
                'name': series.name,
                'description': series.description,
                'year': series.year,
                'genre': series.genre,
                'rating': series.rating,
                'tmdb_id': series.tmdb_id,
                'imdb_id': series.imdb_id,
                'category_id': relation.category.id if relation.category else None,
                'category_name': relation.category.name if relation.category else None,
                'cover': {
                    'id': series.logo.id,
                    'url': series.logo.url,
                    'name': series.logo.name,
                } if series.logo else None,
                'last_refreshed': series.updated_at,
                'custom_properties': series.custom_properties,
                'm3u_account': {
                    'id': relation.m3u_account.id,
                    'name': relation.m3u_account.name,
                    'account_type': relation.m3u_account.account_type
                },
                'episodes_fetched': custom_props.get('episodes_fetched', False),
                'detailed_fetched': custom_props.get('detailed_fetched', False)
            }

            # Always include episodes for series info if they've been fetched
            include_episodes = request.query_params.get('include_episodes', 'true').lower() == 'true'
            if include_episodes and custom_props.get('episodes_fetched', False):
                logger.debug(f"Including episodes for series {series.id}")
                episodes_by_season = {}
                for episode in series.episodes.all().order_by('season_number', 'episode_number'):
                    season_key = str(episode.season_number or 0)
                    if season_key not in episodes_by_season:
                        episodes_by_season[season_key] = []

                    # Get episode relation for additional data
                    episode_relation = M3UEpisodeRelation.objects.filter(
                        episode=episode,
                        m3u_account=relation.m3u_account
                    ).first()

                    episode_data = {
                        'id': episode.id,
                        'uuid': episode.uuid,
                        'name': episode.name,
                        'title': episode.name,
                        'episode_number': episode.episode_number,
                        'season_number': episode.season_number,
                        'description': episode.description,
                        'air_date': episode.air_date,
                        'plot': episode.description,
                        'duration_secs': episode.duration_secs,
                        'rating': episode.rating,
                        'tmdb_id': episode.tmdb_id,
                        'imdb_id': episode.imdb_id,
                        'movie_image': episode.custom_properties.get('movie_image', '') if episode.custom_properties else '',
                        'container_extension': episode_relation.container_extension if episode_relation else 'mp4',
                        'type': 'episode',
                        'series': {
                            'id': series.id,
                            'name': series.name
                        }
                    }
                    episodes_by_season[season_key].append(episode_data)

                response_data['episodes'] = episodes_by_season
                logger.debug(f"Added {len(episodes_by_season)} seasons of episodes to response")
            elif include_episodes:
                # Episodes not yet fetched, include empty episodes list
                response_data['episodes'] = {}

            logger.debug(f"Returning series info response for series {series.id}")
            return Response(response_data)

        except Exception as e:
            logger.error(f"Error fetching series info for series {pk}: {str(e)}")
            return Response(
                {'error': f'Failed to fetch series information: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class VODCategoryFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr="icontains")
    category_type = django_filters.ChoiceFilter(choices=VODCategory.CATEGORY_TYPE_CHOICES)
    m3u_account = django_filters.NumberFilter(field_name="m3u_account__id")

    class Meta:
        model = VODCategory
        fields = ['name', 'category_type', 'm3u_account']


class VODCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for VOD Categories"""
    queryset = VODCategory.objects.all()
    serializer_class = VODCategorySerializer

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = VODCategoryFilter
    search_fields = ['name']
    ordering = ['name']

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]
