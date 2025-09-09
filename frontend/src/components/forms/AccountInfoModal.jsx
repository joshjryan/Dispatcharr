import React from 'react';
import {
  Modal,
  Text,
  Box,
  Group,
  Badge,
  Table,
  Stack,
  Divider,
  Alert,
  Loader,
  Center,
} from '@mantine/core';
import {
  Info,
  Clock,
  Users,
  CheckCircle,
  XCircle,
  AlertTriangle,
} from 'lucide-react';

const AccountInfoModal = ({ isOpen, onClose, profile }) => {
  if (!profile || !profile.custom_properties) {
    return (
      <Modal opened={isOpen} onClose={onClose} title="Account Information">
        <Center p="lg">
          <Stack align="center" spacing="md">
            <Info size={48} color="gray" />
            <Text c="dimmed">No account information available</Text>
            <Text size="sm" c="dimmed" ta="center">
              Account information will be available after the next refresh for
              XtreamCodes accounts.
            </Text>
          </Stack>
        </Center>
      </Modal>
    );
  }

  const { user_info, server_info, last_refresh } = profile.custom_properties;

  // Helper function to format timestamps
  const formatTimestamp = (timestamp) => {
    if (!timestamp) return 'Unknown';
    try {
      const date =
        typeof timestamp === 'string' && timestamp.includes('T')
          ? new Date(timestamp) // This should handle ISO format properly
          : new Date(parseInt(timestamp) * 1000);

      // Convert to user's local time and display with timezone
      return date.toLocaleString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        timeZoneName: 'short',
      });
    } catch {
      return 'Invalid date';
    }
  };

  // Helper function to get time remaining
  const getTimeRemaining = (expTimestamp) => {
    if (!expTimestamp) return null;
    try {
      const expDate = new Date(parseInt(expTimestamp) * 1000);
      const now = new Date();
      const diffMs = expDate - now;

      if (diffMs <= 0) return 'Expired';

      const days = Math.floor(diffMs / (1000 * 60 * 60 * 24));
      const hours = Math.floor(
        (diffMs % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60)
      );

      if (days > 0) {
        return `${days} day${days !== 1 ? 's' : ''} ${hours} hour${hours !== 1 ? 's' : ''}`;
      } else {
        return `${hours} hour${hours !== 1 ? 's' : ''}`;
      }
    } catch {
      return 'Unknown';
    }
  };

  // Helper function to get status badge
  const getStatusBadge = (status) => {
    const statusConfig = {
      Active: { color: 'green', icon: CheckCircle },
      Expired: { color: 'red', icon: XCircle },
      Disabled: { color: 'red', icon: XCircle },
      Banned: { color: 'red', icon: XCircle },
    };

    const config = statusConfig[status] || {
      color: 'gray',
      icon: AlertTriangle,
    };
    const Icon = config.icon;

    return (
      <Badge
        color={config.color}
        variant="light"
        leftSection={<Icon size={12} />}
      >
        {status || 'Unknown'}
      </Badge>
    );
  };

  const timeRemaining = user_info?.exp_date
    ? getTimeRemaining(user_info.exp_date)
    : null;
  const isExpired = timeRemaining === 'Expired';

  return (
    <Modal
      opened={isOpen}
      onClose={onClose}
      title={
        <Group spacing="sm">
          <Info size={20} color="var(--mantine-color-blue-6)" />
          <Text fw={600} size="lg">
            Account Information - {profile.name}
          </Text>
        </Group>
      }
      size="lg"
    >
      <Stack spacing="md">
        {/* Account Status Overview */}
        <Box>
          <Group justify="space-between" mb="sm">
            <Text fw={600} size="lg">
              Account Status
            </Text>
            {getStatusBadge(user_info?.status)}
          </Group>

          {isExpired && (
            <Alert
              icon={<AlertTriangle size={16} />}
              color="red"
              variant="light"
              mb="md"
            >
              This account has expired!
            </Alert>
          )}
        </Box>

        <Divider />

        {/* Key Information Cards */}
        <Group grow>
          <Box
            p="md"
            style={{
              backgroundColor: isExpired
                ? 'rgba(255, 107, 107, 0.08)'
                : 'rgba(64, 192, 87, 0.08)',
              border: `1px solid ${isExpired ? 'rgba(255, 107, 107, 0.2)' : 'rgba(64, 192, 87, 0.2)'}`,
              borderRadius: 8,
            }}
          >
            <Group spacing="xs" mb="xs">
              <Clock
                size={16}
                color={
                  isExpired
                    ? 'var(--mantine-color-red-6)'
                    : 'var(--mantine-color-green-6)'
                }
              />
              <Text fw={500}>Expires</Text>
            </Group>
            <Text size="lg" fw={600} c={isExpired ? 'red' : 'green'}>
              {user_info?.exp_date
                ? formatTimestamp(user_info.exp_date)
                : 'Unknown'}
            </Text>
            {timeRemaining && (
              <Text size="sm" c={isExpired ? 'red' : 'green'}>
                {timeRemaining === 'Expired'
                  ? 'Expired'
                  : `${timeRemaining} remaining`}
              </Text>
            )}
          </Box>

          <Box
            p="md"
            style={{
              backgroundColor: 'rgba(34, 139, 230, 0.08)',
              border: '1px solid rgba(34, 139, 230, 0.2)',
              borderRadius: 8,
            }}
          >
            <Group spacing="xs" mb="xs">
              <Users size={16} color="var(--mantine-color-blue-6)" />
              <Text fw={500}>Connections</Text>
            </Group>
            <Text size="lg" fw={600} c="blue">
              {user_info?.active_cons || '0'} /{' '}
              {user_info?.max_connections || 'Unknown'}
            </Text>
            <Text size="sm" c="dimmed">
              Active / Max
            </Text>
          </Box>
        </Group>

        <Divider />

        {/* Detailed Information Table */}
        <Box>
          <Text fw={600} mb="sm">
            Account Details
          </Text>
          <Table striped highlightOnHover>
            <Table.Tbody>
              <Table.Tr>
                <Table.Td fw={500} w="40%">
                  Username
                </Table.Td>
                <Table.Td>{user_info?.username || 'Unknown'}</Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Td fw={500}>Account Created</Table.Td>
                <Table.Td>
                  {user_info?.created_at
                    ? formatTimestamp(user_info.created_at)
                    : 'Unknown'}
                </Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Td fw={500}>Trial Account</Table.Td>
                <Table.Td>
                  <Badge
                    color={user_info?.is_trial === '1' ? 'orange' : 'blue'}
                    variant="light"
                    size="sm"
                  >
                    {user_info?.is_trial === '1' ? 'Yes' : 'No'}
                  </Badge>
                </Table.Td>
              </Table.Tr>
              {user_info?.allowed_output_formats &&
                user_info.allowed_output_formats.length > 0 && (
                  <Table.Tr>
                    <Table.Td fw={500}>Allowed Formats</Table.Td>
                    <Table.Td>
                      <Group spacing="xs">
                        {user_info.allowed_output_formats.map(
                          (format, index) => (
                            <Badge key={index} variant="outline" size="sm">
                              {format.toUpperCase()}
                            </Badge>
                          )
                        )}
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                )}
            </Table.Tbody>
          </Table>
        </Box>

        {/* Server Information */}
        {server_info && Object.keys(server_info).length > 0 && (
          <>
            <Divider />
            <Box>
              <Text fw={600} mb="sm">
                Server Information
              </Text>
              <Table striped highlightOnHover>
                <Table.Tbody>
                  {server_info.url && (
                    <Table.Tr>
                      <Table.Td fw={500} w="40%">
                        Server URL
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm" family="monospace">
                          {server_info.url}
                        </Text>
                      </Table.Td>
                    </Table.Tr>
                  )}
                  {server_info.port && (
                    <Table.Tr>
                      <Table.Td fw={500}>Port</Table.Td>
                      <Table.Td>
                        <Badge variant="outline" size="sm">
                          {server_info.port}
                        </Badge>
                      </Table.Td>
                    </Table.Tr>
                  )}
                  {server_info.https_port && (
                    <Table.Tr>
                      <Table.Td fw={500}>HTTPS Port</Table.Td>
                      <Table.Td>
                        <Badge variant="outline" size="sm" color="green">
                          {server_info.https_port}
                        </Badge>
                      </Table.Td>
                    </Table.Tr>
                  )}
                  {server_info.timezone && (
                    <Table.Tr>
                      <Table.Td fw={500}>Timezone</Table.Td>
                      <Table.Td>{server_info.timezone}</Table.Td>
                    </Table.Tr>
                  )}
                </Table.Tbody>
              </Table>
            </Box>
          </>
        )}

        {/* Last Refresh Info */}
        <Divider />
        <Box
          p="sm"
          style={{
            backgroundColor: 'rgba(134, 142, 150, 0.08)',
            border: '1px solid rgba(134, 142, 150, 0.2)',
            borderRadius: 6,
          }}
        >
          <Group spacing="xs" align="center">
            <Text fw={500} size="sm">
              Last Account Info Refresh:
            </Text>
            <Badge variant="light" color="gray" size="sm">
              {last_refresh ? formatTimestamp(last_refresh) : 'Never'}
            </Badge>
          </Group>
        </Box>
      </Stack>
    </Modal>
  );
};

export default AccountInfoModal;
