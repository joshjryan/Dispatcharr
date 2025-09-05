import React, { useEffect, useState } from 'react';
import {
  AppShell,
  Box,
  Button,
  Card,
  Group,
  Loader,
  Stack,
  Switch,
  Text,
  TextInput,
  NumberInput,
  Select,
  Divider,
  ActionIcon,
  SimpleGrid,
} from '@mantine/core';
import { RefreshCcw } from 'lucide-react';
import API from '../api';
import { notifications } from '@mantine/notifications';

const Field = ({ field, value, onChange }) => {
  const common = { label: field.label, description: field.help_text };
  const effective = value ?? field.default;
  switch (field.type) {
    case 'boolean':
      return (
        <Switch
          checked={!!effective}
          onChange={(e) => onChange(field.id, e.currentTarget.checked)}
          label={field.label}
          description={field.help_text}
        />
      );
    case 'number':
      return (
        <NumberInput
          value={value ?? field.default ?? 0}
          onChange={(v) => onChange(field.id, v)}
          {...common}
        />
      );
    case 'select':
      return (
        <Select
          value={(value ?? field.default ?? '') + ''}
          data={(field.options || []).map((o) => ({ value: o.value + '', label: o.label }))}
          onChange={(v) => onChange(field.id, v)}
          {...common}
        />
      );
    case 'string':
    default:
      return (
        <TextInput
          value={value ?? field.default ?? ''}
          onChange={(e) => onChange(field.id, e.currentTarget.value)}
          {...common}
        />
      );
  }
};

const PluginCard = ({ plugin, onSaveSettings, onRunAction, onToggleEnabled }) => {
  const [settings, setSettings] = useState(plugin.settings || {});
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [enabled, setEnabled] = useState(plugin.enabled !== false);
  const [lastResult, setLastResult] = useState(null);

  const updateField = (id, val) => {
    setSettings((prev) => ({ ...prev, [id]: val }));
  };

  const save = async () => {
    setSaving(true);
    try {
      await onSaveSettings(plugin.key, settings);
      notifications.show({ title: 'Saved', message: `${plugin.name} settings updated`, color: 'green' });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card shadow="sm" radius="md" withBorder style={{ opacity: enabled ? 1 : 0.6 }}>
      <Group justify="space-between" mb="xs" align="center">
        <div>
          <Text fw={600}>{plugin.name}</Text>
          <Text size="sm" c="dimmed">{plugin.description}</Text>
        </div>
        <Group gap="xs" align="center">
          <Text size="xs" c="dimmed">v{plugin.version || '1.0.0'}</Text>
          <Switch
            checked={enabled}
            onChange={async (e) => {
              const next = e.currentTarget.checked;
              setEnabled(next);
              await onToggleEnabled(plugin.key, next);
            }}
            size="xs"
            onLabel="On"
            offLabel="Off"
          />
        </Group>
      </Group>

      {plugin.fields && plugin.fields.length > 0 && (
        <Stack gap="xs" mt="sm">
          {plugin.fields.map((f) => (
            <Field key={f.id} field={f} value={settings?.[f.id]} onChange={updateField} />
          ))}
          <Group>
            <Button loading={saving} onClick={save} variant="default" size="xs">Save Settings</Button>
          </Group>
        </Stack>
      )}

      {plugin.actions && plugin.actions.length > 0 && (
        <>
          <Divider my="sm" />
          <Stack gap="xs">
            {plugin.actions.map((a) => (
              <Group key={a.id} justify="space-between">
                <div>
                  <Text>{a.label}</Text>
                  {a.description && (
                    <Text size="sm" c="dimmed">{a.description}</Text>
                  )}
                </div>
                <Button
                  loading={running}
                  disabled={!enabled}
                  onClick={async () => {
                    setRunning(true);
                    setLastResult(null);
                    try {
                      // Determine if confirmation is required
                      const confirmField = (plugin.fields || []).find((f) => f.id === 'confirm');
                      let requireConfirm = false;
                      if (confirmField) {
                        const settingVal = settings?.confirm;
                        const effectiveConfirm = (settingVal !== undefined ? settingVal : confirmField.default) ?? false;
                        requireConfirm = !!effectiveConfirm;
                      }

                      if (requireConfirm) {
                        const ok = window.confirm(`Run "${a.label}" from "${plugin.name}"?`);
                        if (!ok) { return; }
                      }

                      // Save settings before running to ensure backend uses latest values
                      try { await onSaveSettings(plugin.key, settings); } catch (e) { /* ignore, run anyway */ }
                      const resp = await onRunAction(plugin.key, a.id);
                      if (resp?.success) {
                        setLastResult(resp.result || {});
                        const msg = resp.result?.message || 'Plugin action completed';
                        notifications.show({ title: plugin.name, message: msg, color: 'green' });
                      } else {
                        const err = resp?.error || 'Unknown error';
                        setLastResult({ error: err });
                        notifications.show({ title: `${plugin.name} error`, message: String(err), color: 'red' });
                      }
                    } finally {
                      setRunning(false);
                    }
                  }}
                  size="xs"
                >
                  {running ? 'Running…' : 'Run'}
                </Button>
              </Group>
            ))}
            {running && (
              <Text size="sm" c="dimmed">Running action… please wait</Text>
            )}
            {!running && lastResult?.file && (
              <Text size="sm" c="dimmed">Output: {lastResult.file}</Text>
            )}
            {!running && lastResult?.error && (
              <Text size="sm" c="red">Error: {String(lastResult.error)}</Text>
            )}
          </Stack>
        </>
      )}
    </Card>
  );
};

export default function PluginsPage() {
  const [loading, setLoading] = useState(true);
  const [plugins, setPlugins] = useState([]);

  const load = async () => {
    setLoading(true);
    try {
      const list = await API.getPlugins();
      setPlugins(list);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <AppShell.Main style={{ padding: 16 }}>
      <Group justify="space-between" mb="md">
        <Text fw={700} size="lg">Plugins</Text>
        <ActionIcon variant="light" onClick={async () => { await API.reloadPlugins(); await load(); }} title="Reload">
          <RefreshCcw size={18} />
        </ActionIcon>
      </Group>

      {loading ? (
        <Loader />
      ) : (
        <>
          <SimpleGrid cols={2} spacing="md" verticalSpacing="md" breakpoints={[{ maxWidth: '48em', cols: 1 }]}> 
            {plugins.map((p) => (
              <PluginCard
                key={p.key}
                plugin={p}
                onSaveSettings={API.updatePluginSettings}
                onRunAction={API.runPluginAction}
                onToggleEnabled={API.setPluginEnabled}
              />
            ))}
          </SimpleGrid>
          {plugins.length === 0 && (
            <Box>
              <Text c="dimmed">No plugins found. Drop a plugin into <code>/app/data/plugins</code> and reload.</Text>
            </Box>
          )}
        </>
      )}
    </AppShell.Main>
  );
}
