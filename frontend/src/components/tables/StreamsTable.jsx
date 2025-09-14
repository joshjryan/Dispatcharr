import React, {
  useEffect,
  useMemo,
  useCallback,
  useState,
  useContext,
} from 'react';
import API from '../../api';
import StreamForm from '../forms/Stream';
import usePlaylistsStore from '../../store/playlists';
import useChannelsStore from '../../store/channels';
import useLogosStore from '../../store/logos';
import { copyToClipboard, useDebounce } from '../../utils';
import { WebsocketContext } from '../../WebSocket';
import {
  SquarePlus,
  ListPlus,
  SquareMinus,
  EllipsisVertical,
  Copy,
  ArrowUpDown,
  ArrowUpNarrowWide,
  ArrowDownWideNarrow,
} from 'lucide-react';
import {
  TextInput,
  ActionIcon,
  Select,
  Tooltip,
  Menu,
  Flex,
  Box,
  Text,
  Paper,
  Button,
  Card,
  Stack,
  Title,
  Divider,
  Center,
  Pagination,
  Group,
  NativeSelect,
  MultiSelect,
  useMantineTheme,
  UnstyledButton,
  LoadingOverlay,
  Skeleton,
} from '@mantine/core';
import { useNavigate } from 'react-router-dom';
import useSettingsStore from '../../store/settings';
import useVideoStore from '../../store/useVideoStore';
import useChannelsTableStore from '../../store/channelsTable';
import { CustomTable, useTable } from './CustomTable';
import useLocalStorage from '../../hooks/useLocalStorage';

const StreamRowActions = ({
  theme,
  row,
  editStream,
  deleteStream,
  handleWatchStream,
  selectedChannelIds,
}) => {
  const [tableSize, _] = useLocalStorage('table-size', 'default');
  const channelSelectionStreams = useChannelsTableStore(
    (state) =>
      state.channels.find((chan) => chan.id === selectedChannelIds[0])?.streams
  );
  const fetchLogos = useLogosStore((s) => s.fetchLogos);

  const createChannelFromStream = async () => {
    const selectedChannelProfileId =
      useChannelsStore.getState().selectedProfileId;

    await API.createChannelFromStream({
      name: row.original.name,
      channel_number: null,
      stream_id: row.original.id,
      // Only pass channel_profile_ids if a specific profile is selected (not "All")
      ...(selectedChannelProfileId !== '0' && {
        channel_profile_ids: selectedChannelProfileId,
      }),
    });
    await API.requeryChannels();
    fetchLogos();
  };

  const addStreamToChannel = async () => {
    await API.updateChannel({
      id: selectedChannelIds[0],
      streams: [
        ...new Set(
          channelSelectionStreams.map((s) => s.id).concat([row.original.id])
        ),
      ],
    });
    await API.requeryChannels();
  };

  const onEdit = useCallback(() => {
    editStream(row.original);
  }, [row.original, editStream]);

  const onDelete = useCallback(() => {
    deleteStream(row.original.id);
  }, [row.original.id, deleteStream]);

  const onPreview = useCallback(() => {
    console.log(
      'Previewing stream:',
      row.original.name,
      'ID:',
      row.original.id,
      'Hash:',
      row.original.stream_hash
    );
    handleWatchStream(row.original.stream_hash);
  }, [row.original, handleWatchStream]); // Add proper dependencies to ensure correct stream

  const iconSize =
    tableSize == 'default' ? 'sm' : tableSize == 'compact' ? 'xs' : 'md';

  return (
    <>
      <Tooltip label="Add to Channel">
        <ActionIcon
          size={iconSize}
          color={theme.tailwind.blue[6]}
          variant="transparent"
          onClick={addStreamToChannel}
          style={{ background: 'none' }}
          disabled={
            selectedChannelIds.length !== 1 ||
            (channelSelectionStreams &&
              channelSelectionStreams
                .map((s) => s.id)
                .includes(row.original.id))
          }
        >
          <ListPlus size="18" fontSize="small" />
        </ActionIcon>
      </Tooltip>

      <Tooltip label="Create New Channel">
        <ActionIcon
          size={iconSize}
          color={theme.tailwind.green[5]}
          variant="transparent"
          onClick={createChannelFromStream}
        >
          <SquarePlus size="18" fontSize="small" />
        </ActionIcon>
      </Tooltip>

      <Menu>
        <Menu.Target>
          <ActionIcon variant="transparent" size={iconSize}>
            <EllipsisVertical size="18" />
          </ActionIcon>
        </Menu.Target>

        <Menu.Dropdown>
          <Menu.Item leftSection={<Copy size="14" />}>
            <UnstyledButton
              variant="unstyled"
              size="xs"
              onClick={() => copyToClipboard(row.original.url)}
            >
              <Text size="xs">Copy URL</Text>
            </UnstyledButton>
          </Menu.Item>
          <Menu.Item onClick={onEdit} disabled={!row.original.is_custom}>
            <Text size="xs">Edit</Text>
          </Menu.Item>
          <Menu.Item onClick={onDelete} disabled={!row.original.is_custom}>
            <Text size="xs">Delete Stream</Text>
          </Menu.Item>
          <Menu.Item onClick={onPreview}>
            <Text size="xs">Preview Stream</Text>
          </Menu.Item>
        </Menu.Dropdown>
      </Menu>
    </>
  );
};

const StreamsTable = () => {
  const theme = useMantineTheme();

  /**
   * useState
   */
  const [allRowIds, setAllRowIds] = useState([]);
  const [stream, setStream] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [groupOptions, setGroupOptions] = useState([]);
  const [initialDataCount, setInitialDataCount] = useState(null);

  const [data, setData] = useState([]); // Holds fetched data
  const [pageCount, setPageCount] = useState(0);
  const [paginationString, setPaginationString] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [sorting, setSorting] = useState([{ id: 'name', desc: '' }]);
  const [selectedStreamIds, setSelectedStreamIds] = useState([]);
  const [isCreatingChannels, setIsCreatingChannels] = useState(false);
  const [creationProgress, setCreationProgress] = useState('');
  const [activeTaskId, setActiveTaskId] = useState(null);

  // WebSocket context for real-time updates
  const [, , wsValue] = useContext(WebsocketContext);
  // const [allRowsSelected, setAllRowsSelected] = useState(false);

  // Add local storage for page size
  const [storedPageSize, setStoredPageSize] = useLocalStorage(
    'streams-page-size',
    50
  );
  const [pagination, setPagination] = useState({
    pageIndex: 0,
    pageSize: storedPageSize,
  });
  const [filters, setFilters] = useState({
    name: '',
    channel_group: '',
    m3u_account: '',
  });
  const [columnSizing, setColumnSizing] = useLocalStorage(
    'streams-table-column-sizing',
    {}
  );
  const debouncedFilters = useDebounce(filters, 500, () => {
    // Reset to first page whenever filters change to avoid "Invalid page" errors
    setPagination((prev) => ({
      ...prev,
      pageIndex: 0,
    }));
  });

  // Add state to track if stream groups are loaded
  const [groupsLoaded, setGroupsLoaded] = useState(false);

  const navigate = useNavigate();

  /**
   * Stores
   */
  const playlists = usePlaylistsStore((s) => s.playlists);

  // Get direct access to channel groups without depending on other data
  const fetchChannelGroups = useChannelsStore((s) => s.fetchChannelGroups);
  const channelGroups = useChannelsStore((s) => s.channelGroups);

  const selectedChannelIds = useChannelsTableStore((s) => s.selectedChannelIds);
  const fetchLogos = useChannelsStore((s) => s.fetchLogos);
  const channelSelectionStreams = useChannelsTableStore(
    (state) =>
      state.channels.find((chan) => chan.id === selectedChannelIds[0])?.streams
  );
  const env_mode = useSettingsStore((s) => s.environment.env_mode);
  const showVideo = useVideoStore((s) => s.showVideo);
  const [tableSize, _] = useLocalStorage('table-size', 'default');

  const handleSelectClick = (e) => {
    e.stopPropagation();
    e.preventDefault();
  };

  /**
   * useMemo
   */
  const columns = useMemo(
    () => [
      {
        id: 'actions',
        size: columnSizing.actions || (tableSize == 'compact' ? 60 : 80),
      },
      {
        id: 'select',
        size: columnSizing.select || 30,
      },
      {
        header: 'Name',
        accessorKey: 'name',
        grow: true,
        size: columnSizing.name || 200,
        cell: ({ getValue }) => (
          <Box
            style={{
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {getValue()}
          </Box>
        ),
      },
      {
        id: 'group',
        accessorFn: (row) =>
          channelGroups[row.channel_group]
            ? channelGroups[row.channel_group].name
            : '',
        size: columnSizing.group || 150,
        cell: ({ getValue }) => (
          <Box
            style={{
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {getValue()}
          </Box>
        ),
      },
      {
        id: 'm3u',
        size: columnSizing.m3u || 150,
        accessorFn: (row) =>
          playlists.find((playlist) => playlist.id === row.m3u_account)?.name,
        cell: ({ getValue }) => (
          <Box
            style={{
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            <Tooltip label={getValue()} openDelay={500}>
              <Box>{getValue()}</Box>
            </Tooltip>
          </Box>
        ),
      },
    ],
    [channelGroups, playlists, columnSizing, tableSize]
  );

  /**
   * Functions
   */
  const handleFilterChange = (e) => {
    const { name, value } = e.target;
    setFilters((prev) => ({
      ...prev,
      [name]: value,
    }));
  };

  const handleGroupChange = (value) => {
    setFilters((prev) => ({
      ...prev,
      channel_group: value ? value : '',
    }));
  };

  const handleM3UChange = (value) => {
    setFilters((prev) => ({
      ...prev,
      m3u_account: value ? value : '',
    }));
  };

  const fetchData = useCallback(async () => {
    setIsLoading(true);

    // Ensure we have channel groups first (if not already loaded)
    if (!groupsLoaded && Object.keys(channelGroups).length === 0) {
      try {
        await fetchChannelGroups();
        setGroupsLoaded(true);
      } catch (error) {
        console.error('Error fetching channel groups:', error);
      }
    }

    const params = new URLSearchParams();
    params.append('page', pagination.pageIndex + 1);
    params.append('page_size', pagination.pageSize);

    // Apply sorting
    if (sorting.length > 0) {
      const sortField = sorting[0].id;
      const sortDirection = sorting[0].desc ? '-' : '';
      params.append('ordering', `${sortDirection}${sortField}`);
    }

    // Apply debounced filters
    Object.entries(debouncedFilters).forEach(([key, value]) => {
      if (value) params.append(key, value);
    });

    try {
      const [result, ids, groups] = await Promise.all([
        API.queryStreams(params),
        API.getAllStreamIds(params),
        API.getStreamGroups(),
      ]);

      setAllRowIds(ids);
      setData(result.results);
      setPageCount(Math.ceil(result.count / pagination.pageSize));
      setGroupOptions(groups);

      // Calculate the starting and ending item indexes
      const startItem = pagination.pageIndex * pagination.pageSize + 1; // +1 to start from 1, not 0
      const endItem = Math.min(
        (pagination.pageIndex + 1) * pagination.pageSize,
        result.count
      );

      if (initialDataCount === null) {
        setInitialDataCount(result.count);
      }

      // Generate the string
      setPaginationString(`${startItem} to ${endItem} of ${result.count}`);
    } catch (error) {
      console.error('Error fetching data:', error);
    }

    setIsLoading(false);
  }, [
    pagination,
    sorting,
    debouncedFilters,
    groupsLoaded,
    channelGroups,
    fetchChannelGroups,
  ]);

  // Bulk creation: create channels from selected streams in one API call
  // Bulk creation: create channels from selected streams asynchronously
  const createChannelsFromStreams = async () => {
    if (selectedStreamIds.length === 0) return;

    setIsCreatingChannels(true);
    setCreationProgress('Starting bulk channel creation...');

    try {
      const selectedChannelProfileId =
        useChannelsStore.getState().selectedProfileId;

      // Use the async API for all bulk operations
      const response = await API.createChannelsFromStreamsAsync(
        selectedStreamIds,
        selectedChannelProfileId !== '0' ? [selectedChannelProfileId] : null
      );

      setActiveTaskId(response.task_id);
      setCreationProgress(
        `Task started for ${response.stream_count} streams. Processing in background...`
      );

      console.log(
        `Bulk creation task started: ${response.task_id} for ${response.stream_count} streams`
      );
      console.log('Active task ID set to:', response.task_id);
    } catch (error) {
      console.error('Error starting bulk channel creation:', error);
      setCreationProgress('Error starting bulk channel creation');
      setIsCreatingChannels(false);
      // Clear error message after delay
      setTimeout(() => setCreationProgress(''), 5000);
    }
  };

  const editStream = async (stream = null) => {
    setStream(stream);
    setModalOpen(true);
  };

  const deleteStream = async (id) => {
    await API.deleteStream(id);
  };

  const deleteStreams = async () => {
    setIsLoading(true);
    await API.deleteStreams(selectedStreamIds);
    setIsLoading(false);
  };

  const closeStreamForm = () => {
    setStream(null);
    setModalOpen(false);
    fetchData();
  };

  const addStreamsToChannel = async () => {
    await API.updateChannel({
      id: selectedChannelIds[0],
      streams: [
        ...new Set(
          channelSelectionStreams.map((s) => s.id).concat(selectedStreamIds)
        ),
      ],
    });
    await API.requeryChannels();
  };

  const onRowSelectionChange = (updatedIds) => {
    setSelectedStreamIds(updatedIds);
  };

  const onPageSizeChange = (e) => {
    const newPageSize = parseInt(e.target.value);
    setStoredPageSize(newPageSize);
    setPagination({
      ...pagination,
      pageSize: newPageSize,
    });
  };

  const onPageIndexChange = (pageIndex) => {
    if (!pageIndex || pageIndex > pageCount) {
      return;
    }

    setPagination({
      ...pagination,
      pageIndex: pageIndex - 1,
    });
  };

  function handleWatchStream(streamHash) {
    let vidUrl = `/proxy/ts/stream/${streamHash}`;
    if (env_mode == 'dev') {
      vidUrl = `${window.location.protocol}//${window.location.hostname}:5656${vidUrl}`;
    }
    showVideo(vidUrl);
  }

  const onSortingChange = (column) => {
    const sortField = sorting[0]?.id;
    const sortDirection = sorting[0]?.desc;

    if (sortField == column) {
      if (sortDirection == false) {
        setSorting([
          {
            id: column,
            desc: true,
          },
        ]);
      } else {
        setSorting([]);
      }
    } else {
      setSorting([
        {
          id: column,
          desc: false,
        },
      ]);
    }
  };

  const renderHeaderCell = (header) => {
    let sortingIcon = ArrowUpDown;
    if (sorting[0]?.id == header.id) {
      if (sorting[0].desc === false) {
        sortingIcon = ArrowUpNarrowWide;
      } else {
        sortingIcon = ArrowDownWideNarrow;
      }
    }

    switch (header.id) {
      case 'name':
        return (
          <Flex gap="sm">
            <TextInput
              name="name"
              placeholder="Name"
              value={filters.name || ''}
              onClick={(e) => e.stopPropagation()}
              onChange={handleFilterChange}
              size="xs"
              variant="unstyled"
              className="table-input-header"
            />
            <Center>
              {React.createElement(sortingIcon, {
                onClick: () => onSortingChange('name'),
                size: 14,
              })}
            </Center>
          </Flex>
        );

      case 'group':
        return (
          <Box onClick={handleSelectClick} style={{ width: '100%' }}>
            <MultiSelect
              placeholder="Group"
              searchable
              size="xs"
              nothingFoundMessage="No options"
              onClick={handleSelectClick}
              onChange={handleGroupChange}
              data={groupOptions}
              variant="unstyled"
              className="table-input-header custom-multiselect"
              clearable
            />
          </Box>
        );

      case 'm3u':
        return (
          <Box onClick={handleSelectClick}>
            <Select
              placeholder="M3U"
              searchable
              clearable
              size="xs"
              nothingFoundMessage="No options"
              onClick={handleSelectClick}
              onChange={handleM3UChange}
              data={playlists.map((playlist) => ({
                label: playlist.name,
                value: `${playlist.id}`,
              }))}
              variant="unstyled"
              className="table-input-header"
            />
          </Box>
        );
    }
  };

  const renderBodyCell = useCallback(
    ({ cell, row }) => {
      switch (cell.column.id) {
        case 'actions':
          return (
            <StreamRowActions
              theme={theme}
              row={row}
              editStream={editStream}
              deleteStream={deleteStream}
              handleWatchStream={handleWatchStream}
              selectedChannelIds={selectedChannelIds}
            />
          );
      }
    },
    [
      selectedChannelIds,
      channelSelectionStreams,
      theme,
      editStream,
      deleteStream,
      handleWatchStream,
    ]
  );

  const table = useTable({
    columns,
    data,
    allRowIds,
    filters,
    pagination,
    sorting,
    columnSizing,
    setColumnSizing,
    onRowSelectionChange: onRowSelectionChange,
    manualPagination: true,
    manualSorting: true,
    manualFiltering: true,
    enableRowSelection: true,
    headerCellRenderFns: {
      name: renderHeaderCell,
      group: renderHeaderCell,
      m3u: renderHeaderCell,
    },
    bodyCellRenderFns: {
      actions: renderBodyCell,
    },
  });

  /**
   * useEffects
   */
  useEffect(() => {
    // Load data independently, don't wait for logos or other data
    fetchData();
  }, [fetchData]);

  // Listen for WebSocket updates for bulk creation progress
  useEffect(() => {
    if (wsValue) {
      console.log('WebSocket message received:', wsValue);

      if (
        wsValue.data &&
        wsValue.data.type === 'bulk_channel_creation_progress'
      ) {
        const data = wsValue.data;
        console.log('Bulk creation progress update:', data);

        // Only handle progress for our active task
        if (activeTaskId && data.task_id === activeTaskId) {
          const progress = data.progress || 0;
          const total = data.total || 0;
          const status = data.status;
          const message = data.message;

          console.log(
            `Task ${activeTaskId} progress: ${progress}/${total} (${status})`
          );

          if (status === 'completed') {
            setCreationProgress(
              `✅ Completed! Created ${data.created_count} channels`
            );
            setIsCreatingChannels(false);
            setActiveTaskId(null);

            // Clear selection and refresh data
            setSelectedStreamIds([]);
            fetchData();
            // Note: API.requeryChannels() is called by WebSocket handler globally

            // Clear success message after delay
            setTimeout(() => setCreationProgress(''), 5000);
          } else if (status === 'failed') {
            setCreationProgress(
              `❌ Task failed: ${data.error || 'Unknown error'}`
            );
            setIsCreatingChannels(false);
            setActiveTaskId(null);

            // Clear error message after longer delay
            setTimeout(() => setCreationProgress(''), 10000);
          } else {
            // Update progress
            const progressPercent =
              total > 0 ? Math.round((progress / total) * 100) : 0;
            setCreationProgress(
              `${message} (${progress}/${total} - ${progressPercent}%)`
            );
          }
        } else {
          console.log(
            `Ignoring progress for task ${data.task_id}, active task is ${activeTaskId}`
          );
        }
      }
    }
  }, [wsValue, activeTaskId, fetchData]);

  return (
    <>
      <Flex
        style={{ display: 'flex', alignItems: 'center', paddingBottom: 12 }}
        gap={15}
      >
        <Text
          w={88}
          h={24}
          style={{
            fontFamily: 'Inter, sans-serif',
            fontWeight: 500,
            fontSize: '20px',
            lineHeight: 1,
            letterSpacing: '-0.3px',
            // color: 'gray.6', // Adjust this to match MUI's theme.palette.text.secondary
            marginBottom: 0,
          }}
        >
          Streams
        </Text>
      </Flex>

      <Paper
        style={{
          height: 'calc(100vh - 60px)',
          backgroundColor: '#27272A',
        }}
      >
        {/* Top toolbar with Remove, Assign, Auto-match, and Add buttons */}
        <Group justify="space-between" style={{ paddingLeft: 10 }}>
          <Box>
            <Button
              leftSection={<SquarePlus size={18} />}
              variant={
                selectedStreamIds.length > 0 && selectedChannelIds.length === 1
                  ? 'light'
                  : 'default'
              }
              size="xs"
              onClick={addStreamsToChannel}
              p={5}
              color={
                selectedStreamIds.length > 0 && selectedChannelIds.length === 1
                  ? theme.tailwind.green[5]
                  : undefined
              }
              style={
                selectedStreamIds.length > 0 && selectedChannelIds.length === 1
                  ? {
                      borderWidth: '1px',
                      borderColor: theme.tailwind.green[5],
                      color: 'white',
                    }
                  : undefined
              }
              disabled={
                !(
                  selectedStreamIds.length > 0 &&
                  selectedChannelIds.length === 1
                )
              }
            >
              Add Streams to Channel
            </Button>
          </Box>

          <Box
            style={{
              display: 'flex',
              justifyContent: 'flex-end',
              padding: 10,
            }}
          >
            <Flex gap={6}>
              <Button
                leftSection={<SquareMinus size={18} />}
                variant="default"
                size="xs"
                onClick={deleteStreams}
                disabled={selectedStreamIds.length == 0}
              >
                Remove
              </Button>

              <Button
                leftSection={<SquarePlus size={18} />}
                variant="default"
                size="xs"
                onClick={createChannelsFromStreams}
                p={5}
                disabled={selectedStreamIds.length == 0 || isCreatingChannels}
                loading={isCreatingChannels}
              >
                {isCreatingChannels
                  ? creationProgress || 'Creating Channels...'
                  : `Create Channels (${selectedStreamIds.length})`}
              </Button>

              <Button
                leftSection={<SquarePlus size={18} />}
                variant="light"
                size="xs"
                onClick={() => editStream()}
                p={5}
                color={theme.tailwind.green[5]}
                style={{
                  borderWidth: '1px',
                  borderColor: theme.tailwind.green[5],
                  color: 'white',
                }}
              >
                Create Stream
              </Button>
            </Flex>
          </Box>
        </Group>

        {initialDataCount === 0 && (
          <Center style={{ paddingTop: 20 }}>
            <Card
              shadow="sm"
              padding="lg"
              radius="md"
              withBorder
              style={{
                backgroundColor: '#222',
                borderColor: '#444',
                textAlign: 'center',
                width: '400px',
              }}
            >
              <Stack align="center">
                <Title order={3} style={{ color: '#d4d4d8' }}>
                  Getting started
                </Title>
                <Text size="sm" color="dimmed">
                  In order to get started, add your M3U or start <br />
                  adding custom streams.
                </Text>
                <Button
                  variant="default"
                  radius="md"
                  size="md"
                  onClick={() => navigate('/sources')}
                  style={{
                    backgroundColor: '#444',
                    color: '#d4d4d8',
                    border: '1px solid #666',
                  }}
                >
                  Add M3U
                </Button>
                <Divider label="or" labelPosition="center" color="gray" />
                <Button
                  variant="default"
                  radius="md"
                  size="md"
                  onClick={() => editStream()}
                  style={{
                    backgroundColor: '#333',
                    color: '#d4d4d8',
                    border: '1px solid #666',
                  }}
                >
                  Add Individual Stream
                </Button>
              </Stack>
            </Card>
          </Center>
        )}
        {initialDataCount > 0 && (
          <Box
            style={{
              display: 'flex',
              flexDirection: 'column',
              height: 'calc(100vh - 100px)',
            }}
          >
            {creationProgress && (
              <Box
                style={{
                  backgroundColor: theme.colors.blue[6],
                  color: 'white',
                  padding: '10px',
                  textAlign: 'center',
                  borderRadius: 'var(--mantine-radius-default)',
                  marginBottom: '10px',
                }}
              >
                <Text size="sm" fw={500}>
                  {creationProgress}
                </Text>
              </Box>
            )}
            <Box
              style={{
                flex: 1,
                overflowY: 'auto',
                overflowX: 'auto',
                border: 'solid 1px rgb(68,68,68)',
                borderRadius: 'var(--mantine-radius-default)',
              }}
            >
              <LoadingOverlay visible={isLoading} />
              <CustomTable table={table} />
            </Box>

            <Box
              style={{
                position: 'sticky',
                bottom: 0,
                zIndex: 3,
                backgroundColor: '#27272A',
              }}
            >
              <Group
                gap={5}
                justify="center"
                style={{
                  padding: 8,
                  borderTop: '1px solid #666',
                }}
              >
                <Text size="xs">Page Size</Text>
                <NativeSelect
                  size="xxs"
                  value={pagination.pageSize}
                  data={['25', '50', '100', '250']}
                  onChange={onPageSizeChange}
                  style={{ paddingRight: 20 }}
                />
                <Pagination
                  total={pageCount}
                  value={pagination.pageIndex + 1}
                  onChange={onPageIndexChange}
                  size="xs"
                  withEdges
                  style={{ paddingRight: 20 }}
                />
                <Text size="xs">{paginationString}</Text>
              </Group>
            </Box>
          </Box>
        )}
      </Paper>
      <StreamForm
        stream={stream}
        isOpen={modalOpen}
        onClose={closeStreamForm}
      />
    </>
  );
};

export default StreamsTable;
