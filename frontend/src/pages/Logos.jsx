import React, { useEffect, useCallback } from 'react';
import { Box, Loader, Center, Text, Stack } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import useLogosStore from '../store/logos';
import LogosTable from '../components/tables/LogosTable';

const LogosPage = () => {
  const { fetchAllLogos, isLoading, needsAllLogos } = useLogosStore();

  const loadLogos = useCallback(async () => {
    try {
      // Only fetch all logos if we haven't loaded them yet
      if (needsAllLogos()) {
        await fetchAllLogos();
      }
    } catch (err) {
      notifications.show({
        title: 'Error',
        message: 'Failed to load logos',
        color: 'red',
      });
      console.error('Failed to load logos:', err);
    }
  }, [fetchAllLogos, needsAllLogos]);

  useEffect(() => {
    loadLogos();
  }, [loadLogos]);

  return (
    <Box style={{ padding: 10 }}>
      {isLoading && (
        <Center style={{ marginBottom: 20 }}>
          <Stack align="center" spacing="sm">
            <Loader size="sm" />
            <Text size="sm" color="dimmed">
              Loading all logos...
            </Text>
          </Stack>
        </Center>
      )}
      <LogosTable />
    </Box>
  );
};

export default LogosPage;
