import dayjs from 'dayjs';

export const PROGRAM_HEIGHT = 90;
export const EXPANDED_PROGRAM_HEIGHT = 180;

export function buildChannelIdMap(channels, tvgsById) {
  const map = new Map();
  channels.forEach((channel) => {
    const tvgRecord = channel.epg_data_id
      ? tvgsById[channel.epg_data_id]
      : null;
    const tvgId = tvgRecord?.tvg_id ?? channel.uuid;
    if (tvgId) {
      map.set(String(tvgId), channel.id);
    }
  });
  return map;
}

export function mapProgramsByChannel(programs, channelIdByTvgId) {
  if (!programs?.length || !channelIdByTvgId?.size) {
    return new Map();
  }

  const map = new Map();
  programs.forEach((program) => {
    const channelId = channelIdByTvgId.get(String(program.tvg_id));
    if (!channelId) {
      return;
    }

    if (!map.has(channelId)) {
      map.set(channelId, []);
    }

    const startMs = program.startMs ?? dayjs(program.start_time).valueOf();
    const endMs = program.endMs ?? dayjs(program.end_time).valueOf();

    map.get(channelId).push({
      ...program,
      startMs,
      endMs,
    });
  });

  map.forEach((list) => {
    list.sort((a, b) => a.startMs - b.startMs);
  });

  return map;
}

export function computeRowHeights(
  filteredChannels,
  programsByChannelId,
  expandedProgramId,
  defaultHeight = PROGRAM_HEIGHT,
  expandedHeight = EXPANDED_PROGRAM_HEIGHT
) {
  if (!filteredChannels?.length) {
    return [];
  }

  return filteredChannels.map((channel) => {
    const channelPrograms = programsByChannelId.get(channel.id) || [];
    const expanded = channelPrograms.some(
      (program) => program.id === expandedProgramId
    );
    return expanded ? expandedHeight : defaultHeight;
  });
}
